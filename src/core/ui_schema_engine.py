"""
UI Schema 引擎

职责：
1. 定义 UI Schema 结构
2. 解析 Schema
3. 根据 Feature Flag 动态过滤
4. 根据 Tenant Context 定制 UI
5. 渲染成 Telegram Inline Keyboard
"""
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


@dataclass
class UISchemaButton:
    """UI Schema 按钮定义"""
    
    text: str                          # 按钮文本
    route: Optional[str] = None        # 路由名称（例如：'v1:group:list'）
    action: Optional[str] = None       # 动作类型（'route', 'url', 'callback'）
    url: Optional[str] = None          # 外部链接
    callback_data: Optional[str] = None  # 自定义回调数据
    
    # 权限控制
    required_permission: Optional[str] = None  # 需要的权限
    required_role: Optional[str] = None        # 需要的角色
    
    # 功能开关（旧方式，向后兼容）
    feature_flag: Optional[str] = None         # 功能开关名称
    
    # 🆕 Capability System（替代 feature_flag）
    required_capabilities: Optional[List[str]] = None  # 需要的能力列表（例如：['feature.ai']）
    
    # 显示条件
    visible_if: Optional[Dict[str, Any]] = None  # 显示条件（键值对）
    
    # 样式
    style: Optional[str] = None          # 样式（'primary', 'secondary', 'danger'）
    icon: Optional[str] = None           # 图标 emoji
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'text': self.text,
            'route': self.route,
            'action': self.action or 'route',
            'url': self.url,
            'callback_data': self.callback_data,
            'required_permission': self.required_permission,
            'required_role': self.required_role,
            'feature_flag': self.feature_flag,
            'required_capabilities': self.required_capabilities,  # 🆕
            'visible_if': self.visible_if,
            'style': self.style,
            'icon': self.icon
        }


@dataclass
class UISchemaSection:
    """UI Schema 区块"""
    
    title: Optional[str] = None              # 区块标题
    buttons: List[UISchemaButton] = field(default_factory=list)  # 按钮列表
    layout: str = "grid"                     # 布局方式（'grid', 'list', 'inline'）
    columns: int = 2                         # 列数（仅 grid 布局有效）
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'title': self.title,
            'buttons': [btn.to_dict() for btn in self.buttons],
            'layout': self.layout,
            'columns': self.columns
        }


@dataclass
class UISchema:
    """UI Schema 完整定义"""
    
    page: str                                # 页面标识（例如：'group_manage'）
    version: str = "v1"                      # 版本号
    title: Optional[str] = None              # 页面标题
    description: Optional[str] = None        # 页面描述
    sections: List[UISchemaSection] = field(default_factory=list)  # 区块列表
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'page': self.page,
            'version': self.version,
            'title': self.title,
            'description': self.description,
            'sections': [section.to_dict() for section in self.sections],
            'metadata': self.metadata
        }


class UISchemaEngine:
    """
    UI Schema 引擎
    
    负责：
    1. 加载 UI Schema
    2. 根据 Feature Flag 过滤按钮
    3. 根据权限过滤按钮
    4. 渲染成 Telegram Inline Keyboard
    """
    
    def __init__(self):
        # Schema 缓存：{page_name: UISchema}
        self.schema_cache: Dict[str, UISchema] = {}
        
        # 注册默认 Schema
        self._register_default_schemas()
    
    def _register_default_schemas(self):
        """注册默认的 UI Schema"""
        
        # === 主菜单 ===
        # 根据脑图权限设计：
        # - 超级管理员/Bot创建者: 使用说明、广播用户、运行统计、分组管理、功能设置、群发广播、个人中心、能量TRX、USDT监听
        # - 管理员: 使用说明、创建续费、运行统计、分组管理、功能设置、群发广播、个人中心、能量TRX、USDT监听
        # - 普通用户: 使用说明、创建续费、功能设置、联系客服、能量TRX、USDT监听
        main_menu_schema = UISchema(
            page="main_menu",
            version="v2",
            title="🏠 主菜单",
            sections=[
                UISchemaSection(
                    title="常用功能",
                    buttons=[
                        # 📢 广播用户 - 超级管理员、Bot创建者可见
                        UISchemaButton(
                            text="📢 广播用户",
                            route="v1:broadcast:users",
                            icon="📢",
                            visible_if={"user_role_in": ["super_admin", "bot_owner"]}
                        ),
                        # 💰 创建续费 - 管理员、普通用户可见
                        UISchemaButton(
                            text="💰 创建续费",
                            route="v1:billing:self_renew",
                            icon="💰",
                            visible_if={"user_role_in": ["admin", "normal_user"]}
                        ),
                        # 📊 运行统计 - 超级管理员、Bot创建者、管理员可见
                        UISchemaButton(
                            text="📊 运行统计",
                            route="v1:stats:runtime",
                            icon="📊",
                            visible_if={"user_role_in": ["super_admin", "bot_owner", "admin"]}
                        ),
                        # 📁 分组管理 - 超级管理员、Bot创建者、管理员可见
                        UISchemaButton(
                            text="📁 分组管理",
                            route="v1:group:manage",
                            icon="📁",
                            visible_if={"user_role_in": ["super_admin", "bot_owner", "admin"]}
                        ),
                        # 📝 申请试用 - 普通用户可见
                        UISchemaButton(
                            text="📝 申请试用",
                            route="v1:menu:apply_trial",
                            icon="📝",
                            visible_if={"user_role_in": ["normal_user"]}
                        ),
                        # ⚙️ 功能设置 - 所有用户可见
                        UISchemaButton(
                            text="⚙️ 功能设置",
                            route="v1:settings:main",
                            icon="⚙️"
                        ),
                        # 👤 个人中心 - 超级管理员、Bot创建者、管理员可见
                        UISchemaButton(
                            text="👤 个人中心",
                            route="v1:menu:personal_center",
                            icon="👤",
                            visible_if={"user_role_in": ["super_admin", "bot_owner", "admin"]}
                        ),
                        # 💬 联系客服 - 普通用户可见
                        UISchemaButton(
                            text="💬 联系客服",
                            route="v1:menu:contact_support",
                            icon="💬",
                            visible_if={"user_role_in": ["normal_user"]}
                        ),
                        # ⚡ 能量TRX - 所有用户可见
                        UISchemaButton(
                            text="⚡ 能量TRX",
                            route="v1:energy:trx",
                            icon="⚡"
                        ),
                        # 💰 USDT监听 - 所有用户可见
                        UISchemaButton(
                            text="💰 USDT监听",
                            route="v1:usdt:monitor",
                            icon="💰"
                        ),
                    ],
                    layout="grid",
                    columns=3
                )
            ]
        )
        self.schema_cache["main_menu"] = main_menu_schema
        
        # === 群组管理 ===
        group_manage_schema = UISchema(
            page="group_manage",
            version="v1",
            title="📡 分组管理",
            sections=[
                UISchemaSection(
                    title="分组操作",
                    buttons=[
                        UISchemaButton(
                            text="📁 查看分组",
                            route="v1:group:list",
                            icon="📁"
                        ),
                        UISchemaButton(
                            text="➕ 创建分组",
                            route="v1:group:create",
                            icon="➕",
                            required_permission="can_manage_group_members"
                        ),
                        UISchemaButton(
                            text="🗑️ 删除分组",
                            route="v1:group:delete",
                            icon="🗑️",
                            required_permission="can_manage_group_members",
                            style="danger"
                        ),
                    ],
                    layout="list",
                    columns=1
                )
            ]
        )
        self.schema_cache["group_manage"] = group_manage_schema
        
        # === 设置菜单 ===
        # 根据脑图设计：功能设置菜单（支持权限分级）
        # - Bot创建者专属: 添加管理员、授权群组
        # - Bot创建者 + 管理员: 全局日切、全局记账条数、全局记账成员名字、全局欢迎语、关键词、分组管理、群发广播
        # - 无权限限制: 用户更名检测
        settings_menu_schema = UISchema(
            page="settings_menu",
            version="v2",
            title="⚙️ 功能设置",
            sections=[
                UISchemaSection(
                    title="全局配置（Bot创建者和管理员）",
                    buttons=[
                        # 全局日切设置
                        UISchemaButton(
                            text="✂️ 全局日切设置",
                            route="v1:settings:daycut_global",
                            icon="✂️"
                        ),
                        # 全局记账条数设置
                        UISchemaButton(
                            text="📊 全局记账条数设置",
                            route="v1:settings:display_count_global",
                            icon="📊"
                        ),
                        # 全局记账成员名字显示
                        UISchemaButton(
                            text="👤 全局记账成员名字显示",
                            route="v1:settings:show_name_global",
                            icon="👤"
                        ),
                    ],
                    layout="list",
                    columns=1
                ),
                UISchemaSection(
                    title="功能配置（Bot创建者和管理员）",
                    buttons=[
                        UISchemaButton(
                            text="📢 用户广播",
                            route="v1:broadcast:users",
                            icon="📢"
                        ),
                        # 全局入群欢迎语
                        UISchemaButton(
                            text="👋 全局入群欢迎语",
                            route="v1:settings:welcome_global",
                            icon="👋"
                        ),
                        # 全局关键词设置
                        UISchemaButton(
                            text="💬 全局关键词设置",
                            route="v1:settings:keyword_global",
                            icon="💬"
                        ),
                        # 分组管理
                        UISchemaButton(
                            text="📁 分组管理",
                            route="v1:group:manage",
                            icon="📁"
                        ),
                    ],
                    layout="list",
                    columns=1
                ),
                UISchemaSection(
                    title="Bot创建者专属",
                    buttons=[
                        # 添加管理员
                        UISchemaButton(
                            text="👥 添加管理员",
                            route="v1:admin:add",
                            icon="👥"
                        ),
                        # 授权群组
                        UISchemaButton(
                            text="🔐 授权群组",
                            route="v1:admin:authorize_group",
                            icon="🔐"
                        ),
                    ],
                    layout="list",
                    columns=1
                ),
                UISchemaSection(
                    title="其他设置",
                    buttons=[
                        # 用户更名检测
                        UISchemaButton(
                            text="🍀 用户更名检测",
                            route="v1:settings:rename_notification",
                            icon="🍀"
                        ),
                    ],
                    layout="list",
                    columns=1
                )
            ]
        )
        self.schema_cache["settings_menu"] = settings_menu_schema
        
        # === 全局日切设置 ===
        daycut_global_schema = UISchema(
            page="settings_daycut_global",
            version="v1",
            title="✂️ 全局日切设置",
            description="设置每日定时切换账单的时间，对所有授权群组生效",
            sections=[]
        )
        self.schema_cache["settings_daycut_global"] = daycut_global_schema
        
        # === 全局记账条数设置 ===
        display_count_global_schema = UISchema(
            page="settings_display_count_global",
            version="v1",
            title="📊 全局记账条数设置",
            description="设置全局默认的记账显示条数",
            sections=[]
        )
        self.schema_cache["settings_display_count_global"] = display_count_global_schema
        
        # === 全局记账成员名字显示 ===
        show_name_global_schema = UISchema(
            page="settings_show_name_global",
            version="v1",
            title="👤 全局记账成员名字显示",
            description="设置是否在账单中显示成员名字",
            sections=[]
        )
        self.schema_cache["settings_show_name_global"] = show_name_global_schema
        
        # === 全局入群欢迎语 ===
        welcome_global_schema = UISchema(
            page="settings_welcome_global",
            version="v1",
            title="👋 全局入群欢迎语",
            description="设置新用户入群时的欢迎消息",
            sections=[]
        )
        self.schema_cache["settings_welcome_global"] = welcome_global_schema
        
        # === 全局关键词设置 ===
        keyword_global_schema = UISchema(
            page="settings_keyword_global",
            version="v1",
            title="💬 全局关键词设置",
            description="设置全局关键词自动回复",
            sections=[]
        )
        self.schema_cache["settings_keyword_global"] = keyword_global_schema
        
        # === 用户更名检测 ===
        rename_notification_schema = UISchema(
            page="settings_rename_notification",
            version="v1",
            title="🍀 用户更名检测",
            description="设置用户更名时的检测和提醒",
            sections=[]
        )
        self.schema_cache["settings_rename_notification"] = rename_notification_schema
        
        # === 个人中心 ===
        personal_center_schema = UISchema(
            page="personal_center",
            version="v1",
            title="👤 个人中心",
            description="查看您的账户信息和权限",
            sections=[
                UISchemaSection(
                    title="账户信息",
                    buttons=[
                        UISchemaButton(
                            text="📊 我的统计",
                            route="v1:personal:stats",
                            icon="📊"
                        ),
                        UISchemaButton(
                            text="🔔 通知设置",
                            route="v1:personal:notifications",
                            icon="🔔"
                        ),
                    ],
                    layout="grid",
                    columns=2
                )
            ]
        )
        self.schema_cache["personal_center"] = personal_center_schema
        
        # === 使用说明 ===
        usage_guide_schema = UISchema(
            page="usage_guide",
            version="v1",
            title="📖 使用说明",
            description="如何使用记账机器人",
            sections=[]  # 纯文本说明，无需按钮
        )
        self.schema_cache["usage_guide"] = usage_guide_schema
        
        # === 联系客服 ===
        contact_support_schema = UISchema(
            page="contact_support",
            version="v1",
            title=" 联系客服",
            description="如需帮助，请联系客服",
            sections=[]  # 纯文本说明，无需按钮
        )
        self.schema_cache["contact_support"] = contact_support_schema
        
        # === 自助续费 ===
        self_renew_schema = UISchema(
            page="self_renew",
            version="v1",
            title="💰 自助续费",
            description="续费您的机器人服务",
            sections=[
                UISchemaSection(
                    title="续费操作",
                    buttons=[
                        UISchemaButton(
                            text="📋 查看套餐",
                            route="v1:billing:plans",
                            icon="📋"
                        ),
                        UISchemaButton(
                            text="💳 立即续费",
                            route="v1:billing:renew",
                            icon="💳",
                            required_permission="can_renew"
                        ),
                    ],
                    layout="grid",
                    columns=2
                )
            ]
        )
        self.schema_cache["self_renew"] = self_renew_schema
        
        # === 群发广播 ===
        broadcast_send_schema = UISchema(
            page="broadcast_send",
            version="v1",
            title="📢 群发广播",
            description="向群组发送广播消息",
            sections=[
                UISchemaSection(
                    title="广播操作",
                    buttons=[
                        UISchemaButton(
                            text=" 新建广播",
                            route="v1:broadcast:new",
                            icon="📝"
                        ),
                        UISchemaButton(
                            text="📊 广播记录",
                            route="v1:broadcast:history",
                            icon=""
                        ),
                    ],
                    layout="grid",
                    columns=2
                )
            ]
        )
        self.schema_cache["broadcast_send"] = broadcast_send_schema
        
        # === 能量 TRX ===
        energy_trx_schema = UISchema(
            page="energy_trx",
            version="v1",
            title="⚡ 能量 TRX",
            description="TRX 能量管理",
            sections=[
                UISchemaSection(
                    title="能量操作",
                    buttons=[
                        UISchemaButton(
                            text=" 查看能量",
                            route="v1:energy:view",
                            icon="🔋"
                        ),
                        UISchemaButton(
                            text="⚡ 获取能量",
                            route="v1:energy:acquire",
                            icon="⚡"
                        ),
                    ],
                    layout="grid",
                    columns=2
                )
            ]
        )
        self.schema_cache["energy_trx"] = energy_trx_schema
        
        # === USDT 监听 ===
        usdt_monitor_schema = UISchema(
            page="usdt_monitor",
            version="v1",
            title=" USDT 监听",
            description="USDT 支付监听管理",
            sections=[
                UISchemaSection(
                    title="监听操作",
                    buttons=[
                        UISchemaButton(
                            text="▶️ 开启监听",
                            route="v1:usdt:start",
                            icon="▶️"
                        ),
                        UISchemaButton(
                            text="⏹️ 关闭监听",
                            route="v1:usdt:stop",
                            icon="⏹️"
                        ),
                        UISchemaButton(
                            text="📊 监听状态",
                            route="v1:usdt:status",
                            icon=""
                        ),
                    ],
                    layout="grid",
                    columns=2
                )
            ]
        )
        self.schema_cache["usdt_monitor"] = usdt_monitor_schema
        
        # === 创建机器人 ===
        create_bot_schema = UISchema(
            page="create_bot",
            version="v1",
            title="🤖 创建机器人",
            description="创建您的专属记账机器人",
            sections=[
                UISchemaSection(
                    title="创建流程",
                    buttons=[
                        UISchemaButton(
                            text="📋 选择套餐",
                            route="v1:saas:plans",
                            icon="📋"
                        ),
                        UISchemaButton(
                            text="🚀 开始创建",
                            route="v1:saas:create",
                            icon=""
                        ),
                    ],
                    layout="grid",
                    columns=2
                )
            ]
        )
        self.schema_cache["create_bot"] = create_bot_schema
    
    def get_schema(self, page: str) -> Optional[UISchema]:
        """
        获取 UI Schema
        
        Args:
            page: 页面标识
            
        Returns:
            UISchema 对象，如果不存在则返回 None
        """
        return self.schema_cache.get(page)
    
    def filter_schema(
        self,
        schema: UISchema,
        tenant_context,
        feature_flags: Optional[Dict[str, bool]] = None
    ) -> UISchema:
        """
        根据权限和 Capability 过滤 Schema
        
        Args:
            schema: 原始 Schema
            tenant_context: 租户上下文
            feature_flags: 功能开关字典（向后兼容）
            
        Returns:
            过滤后的 Schema
        """
        from copy import deepcopy
        filtered_schema = deepcopy(schema)
        
        # 获取租户 ID 和用户 ID
        tenant_id = tenant_context.bot_id if tenant_context else None
        user_id = str(tenant_context.owner_id) if tenant_context else None
        
        # 遍历所有区块和按钮
        for section in filtered_schema.sections:
            filtered_buttons = []
            
            for button in section.buttons:
                # 🆕 检查 Capability（新方式）
                if button.required_capabilities:
                    from .capability_system import capability_resolver
                    
                    has_all_capabilities = True
                    for cap_name in button.required_capabilities:
                        if not capability_resolver.has_capability(
                            capability_name=cap_name,
                            tenant_id=tenant_id,
                            user_id=user_id
                        ):
                            has_all_capabilities = False
                            logger.debug(f"Button '{button.text}' hidden by missing capability '{cap_name}'")
                            break
                    
                    if not has_all_capabilities:
                        continue
                
                # 向后兼容：检查 Feature Flag（旧方式）
                elif button.feature_flag:
                    flag_enabled = False
                    
                    # 优先使用传入的 feature_flags
                    if feature_flags and button.feature_flag in feature_flags:
                        flag_enabled = feature_flags[button.feature_flag]
                    # 否则使用 tenant_context
                    elif tenant_context:
                        flag_enabled = tenant_context.is_feature_enabled(button.feature_flag)
                    
                    if not flag_enabled:
                        logger.debug(f"Button '{button.text}' hidden by feature flag '{button.feature_flag}'")
                        continue
                
                # 检查权限
                if button.required_permission and tenant_context:
                    if not tenant_context.has_permission(button.required_permission):
                        logger.debug(f"Button '{button.text}' hidden by permission '{button.required_permission}'")
                        continue
                
                # 检查显示条件
                if button.visible_if and tenant_context:
                    should_show = True
                    for key, value in button.visible_if.items():
                        if key == "user_role_in":
                            # 特殊处理：检查用户角色是否在列表中
                            user_role = getattr(tenant_context, 'user_role', None)
                            if user_role not in value:
                                should_show = False
                                break
                        else:
                            # 从 tenant_context.config_snapshot 中获取值
                            config_value = tenant_context.config_snapshot.get(key)
                            if config_value != value:
                                should_show = False
                                break
                    
                    if not should_show:
                        logger.debug(f"Button '{button.text}' hidden by visible_if condition")
                        continue
                
                filtered_buttons.append(button)
            
            section.buttons = filtered_buttons
        
        return filtered_schema
    
    def render_keyboard(
        self,
        schema: UISchema,
        tenant_context=None,
        feature_flags: Optional[Dict[str, bool]] = None
    ) -> InlineKeyboardMarkup:
        """
        渲染成 Telegram Inline Keyboard
        
        Args:
            schema: UI Schema
            tenant_context: 租户上下文
            feature_flags: 功能开关字典
            
        Returns:
            InlineKeyboardMarkup 对象
        """
        # 过滤 Schema
        filtered_schema = self.filter_schema(schema, tenant_context, feature_flags)
        
        keyboard = []
        
        # 遍历所有区块
        for section in filtered_schema.sections:
            if not section.buttons:
                continue
            
            # 根据布局方式渲染
            if section.layout == "grid":
                # 网格布局：每行 columns 个按钮
                columns = section.columns
                for i in range(0, len(section.buttons), columns):
                    row = []
                    for button in section.buttons[i:i+columns]:
                        row.append(self._create_button(button))
                    keyboard.append(row)
            
            elif section.layout == "list":
                # 列表布局：每个按钮一行
                for button in section.buttons:
                    keyboard.append([self._create_button(button)])
            
            elif section.layout == "inline":
                # 内联布局：所有按钮在一行
                row = [self._create_button(button) for button in section.buttons]
                keyboard.append(row)
        
        return InlineKeyboardMarkup(keyboard)
    
    def _create_button(self, button: UISchemaButton) -> InlineKeyboardButton:
        """
        创建单个按钮
        
        Args:
            button: 按钮定义
            
        Returns:
            InlineKeyboardButton 对象
        """
        # 添加图标
        text = button.text
        if button.icon and button.icon not in text:
            text = f"{button.icon} {text}"
        
        # 根据动作类型创建按钮
        if button.action == "url" and button.url:
            return InlineKeyboardButton(text=text, url=button.url)
        
        elif button.action == "callback" and button.callback_data:
            return InlineKeyboardButton(text=text, callback_data=button.callback_data)
        
        else:
            # 默认使用 route
            callback_data = button.route or button.callback_data or "unknown"
            return InlineKeyboardButton(text=text, callback_data=callback_data)
    
    def register_schema(self, page: str, schema: UISchema):
        """
        注册自定义 Schema
        
        Args:
            page: 页面标识
            schema: UI Schema
        """
        self.schema_cache[page] = schema
        logger.info(f"Registered UI schema for page: {page}")


# 全局实例
ui_schema_engine = UISchemaEngine()
