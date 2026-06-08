"""
格式化工具
"""
from datetime import datetime
from typing import List, Optional
import pytz


class Formatter:
    """消息格式化器"""

    @staticmethod
    def escape_markdown_v1(text: str) -> str:
        """转义 Markdown V1 特殊字符，防止 Telegram 解析错误"""
        if not text:
            return text
        # Markdown V1 需要转义: _ * [ ] ( ) ~ ` > # + - = | { } . !
        escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in escape_chars:
            text = text.replace(char, f"\\{char}")
        return text

    @staticmethod
    def escape_html(text: str) -> str:
        """转义 HTML 特殊字符，防止 Telegram 解析错误"""
        if not text:
            return text
        # HTML 需要转义: & < >
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        return text

    @staticmethod
    def _format_time_to_beijing(raw_time):
        """
        将时间转换为北京时间并格式化为 HH:MM:SS
        
        Args:
            raw_time: datetime对象（可能是UTC时间或naive时间）
            
        Returns:
            str: 格式化后的时间字符串 "HH:MM:SS"
        """
        if not raw_time:
            return "--:--:--"
        
        try:
            # 如果时间是naive（无时区信息），假设是UTC时间并转换为北京时间
            if raw_time.tzinfo is None:
                utc_time = pytz.utc.localize(raw_time)
                beijing_time = utc_time.astimezone(pytz.timezone('Asia/Shanghai'))
            else:
                # 已有timezone信息，直接转换
                beijing_time = raw_time.astimezone(pytz.timezone('Asia/Shanghai'))
            
            return beijing_time.strftime("%H:%M:%S")
        except Exception:
            # 如果转换失败，返回原始时间的小时、分钟和秒
            return raw_time.strftime("%H:%M:%S")

    @staticmethod
    def format_transaction(trans, display_mode: str = "pure", currency_mode: str = "single", group_name: str = None) -> str:
        """
        格式化单条交易记录

        Args:
            trans: 交易记录对象
            display_mode: 显示模式 (pure/reply/operator)
            currency_mode: 币种模式 (single/dual)
            group_name: 群组名称（可选）
        """
        lines = []

        # 顶部：群组名称和日期
        if group_name:
            lines.append(f"📌 {group_name}")
        
        date_str = trans.transaction_date.strftime("%Y-%m-%d")
        time_str = trans.transaction_date.strftime("%H:%M:%S")
        lines.append(f"📅 日期：{date_str} {time_str}")
        lines.append("")

        # 交易类型标记
        if trans.transaction_type == 'deposit':
            type_mark = "💰 入款"
        elif trans.transaction_type == 'withdraw':
            type_mark = "💸 下发"
        else:
            type_mark = "📦 寄存"

        # 操作人信息
        operator_display = trans.operator_first_name or trans.operator_username or f"用户{trans.operator_id}"
        lines.append(f"👤 操作人：{operator_display}")
        lines.append("")

        # 被记账人信息
        user_display = trans.first_name or trans.username or f"用户{trans.user_id}"
        lines.append(f"👥 记账给：{user_display}")
        lines.append("")

        # 金额信息
        if currency_mode == "dual":
            if trans.currency == "USDT":
                lines.append(f"💵 USDT金额：{trans.amount:.2f} USDT")
                if trans.cny_amount:
                    lines.append(f"💴 人民币金额：¥{trans.cny_amount:.2f}")
            else:
                lines.append(f"💴 人民币金额：¥{trans.amount:.2f}")
        else:
            lines.append(f"💵 金额：{trans.amount:.2f} {trans.currency}")
            if trans.cny_amount and trans.currency == "USDT":
                lines.append(f"💴 人民币金额：¥{trans.cny_amount:.2f}")

        lines.append("")

        # 汇率和费率信息
        rate_info = []
        if trans.exchange_rate:
            rate_info.append(f"汇率：{trans.exchange_rate}")
        if trans.fee_rate:
            rate_info.append(f"费率：{trans.fee_rate}%")
        
        if rate_info:
            lines.append("⚙️ " + " | ".join(rate_info))
            lines.append("")

        # 手续费和实际到账
        if trans.fee_amount is not None and trans.final_amount is not None:
            lines.append(f"💸 手续费：¥{trans.fee_amount:.2f}")
            lines.append(f"✅ 实际到账：¥{trans.final_amount:.2f}")
            lines.append("")

        # 备注
        if trans.note:
            lines.append(f"📝 备注：{trans.note}")
            lines.append("")

        # 底部分隔线
        lines.append("━━━━━━━━━━━━━━━━━━━━")

        return "\n".join(lines)

    @staticmethod
    def format_transaction_list(
        transactions: List,
        title: str = "账单列表",
        display_mode: str = "pure",
        currency_mode: str = "single",
        limit: Optional[int] = None
    ) -> str:
        """
        格式化交易列表
        """
        if not transactions:
            return f"📋 {title}\n\n暂无记录"

        lines = [f"📋 {title}", "=" * 30]

        display_transactions = transactions[:limit] if limit else transactions

        for i, trans in enumerate(display_transactions, 1):
            lines.append(f"\n[{i}]")
            lines.append(Formatter.format_transaction(trans, display_mode, currency_mode))

        if limit and len(transactions) > limit:
            lines.append(f"\n... 还有 {len(transactions) - limit} 条记录")

        return "\n".join(lines)

    @staticmethod
    def format_summary(summary: dict, title: str = "账单汇总") -> str:
        """
        格式化账单汇总
        """
        lines = [
            f"📊 {title}",
            "=" * 30,
            "",
            f"💰 入款: {summary['deposit_count']}笔",
            f"   总额: {summary['deposit_amount']:.2f} USDT",
            f"   人民币: ¥{summary['deposit_cny']:.2f}",
            "",
            f"💸 下发: {summary['withdraw_count']}笔",
            f"   总额: {summary['withdraw_amount']:.2f} USDT",
            f"   人民币: ¥{summary['withdraw_cny']:.2f}",
            "",
            f"📦 寄存: ¥{summary['storage_amount']:.2f}",
            "",
            f"💵 手续费: ¥{summary['total_fee']:.2f}",
            "",
            f"📈 净额: ¥{summary['net_amount']:.2f}",
        ]
        return "\n".join(lines)

    @staticmethod
    def format_group_config(group) -> str:
        """
        格式化群组配置信息
        """
        status = "✅ 开启" if group.is_active else "❌ 停止"
        mute = "🔇 禁言中" if group.is_muted else "🔊 可发言"

        display_modes = {
            "pure": "纯净模式",
            "reply": "显示回复人",
            "operator": "显示操作人"
        }

        currency_modes = {
            "single": "单币模式",
            "dual": "双币模式"
        }

        lines = [
            f"⚙️ 群组配置 - {group.group_name}",
            "=" * 30,
            "",
            f"📌 状态: {status}",
            f"🔊 发言: {mute}",
            "",
            f"💱 汇率: {group.exchange_rate}",
            f"💰 费率: {group.fee_rate}%",
            "",
            f"📺 显示模式: {display_modes.get(group.display_mode, group.display_mode)}",
            f"💵 币种模式: {currency_modes.get(group.currency_mode, group.currency_mode)}",
            f"🏷️ 显示币种: {group.currency_display}",
            f"📍 置顶: {'开启' if group.pin_enabled else '关闭'}",
            "",
            f"📊 入款显示: {group.deposit_display_count}条",
            f"📊 下发显示: {group.withdraw_display_count}条",
            "",
            f"🔖 分类: {'开启' if group.category_enabled else '关闭'}",
        ]

        if group.day_cut_time:
            lines.append(f"⏰ 日切时间: {group.day_cut_time.strftime('%H:%M')}")

        if group.group_tag:
            lines.append(f"🏷️ 分组: {group.group_tag}")

        if group.withdraw_address:
            lines.append(f"📫 下发地址: {group.withdraw_address}")

        return "\n".join(lines)

    @staticmethod
    def format_operators(operators: List, global_operators: List = None, chat_creator=None) -> str:
        """
        格式化操作人列表
        
        Args:
            operators: 群组操作人列表
            global_operators: 全局操作人列表
            chat_creator: 群主信息（Telegram User 对象，拉bot进群的用户）
        """
        # 群组中的显示格式（图1风格）- 始终显示本群权限列表格式
        lines = [" <b>本群权限列表：</b>", ""]

        # 主管理员显示逻辑：优先使用 chat_creator（群主），其次使用第一个全局操作人
        main_admin = None
        if chat_creator:
            main_admin = chat_creator
        elif global_operators:
            main_admin = global_operators[0]
        
        if main_admin:
            if main_admin.username:
                admin_display = f"@{main_admin.username}"
            elif main_admin.first_name:
                admin_display = main_admin.first_name
            else:
                admin_display = f"用户{main_admin.user_id}"
            lines.append(f"👨‍💼 <b>主管理员</b>: {admin_display}")

        if operators:
            # 去重：基于 user_id 去重
            seen_user_ids = set()
            unique_operators = []
            for op in operators:
                if op.user_id not in seen_user_ids:
                    seen_user_ids.add(op.user_id)
                    unique_operators.append(op)
            
            lines.append("")
            lines.append("✨ <b>操作员列表：</b>")
            for i, op in enumerate(unique_operators, 1):
                if op.username:
                    user_display = f"@{op.username}"
                elif op.first_name:
                    user_display = op.first_name
                else:
                    user_display = f"用户{op.user_id}"
                lines.append(f"{i}. {user_display}")

        if not operators and not chat_creator:
            lines.append("暂无权限人员")

        return "\n".join(lines)

    @staticmethod
    def format_user_configs(configs: List) -> str:
        """
        格式化用户配置列表（费汇配置）
        """
        if not configs:
            return "📋 费汇配置\n\n暂无个人配置"

        lines = ["📋 费汇配置", "=" * 30]

        for config in configs:
            user_display = config.first_name or config.username or f"用户{config.user_id}"
            lines.append(f"\n👤 {user_display}:")
            if config.exchange_rate:
                lines.append(f"   汇率: {config.exchange_rate}")
            if config.fee_rate:
                lines.append(f"   费率: {config.fee_rate}%")

        return "\n".join(lines)
    
    @staticmethod
    def format_user_complete_bill(
        deposits: List,
        withdraws: List,
        summary: dict,
        group_name: str = "记账机器人",
        user_name: str = "我",
        currency: str = "USDT",
        group_exchange_rate: float = None,
        group_fee_rate: float = None,
        display_mode: str = "pure",
        show_member_name: bool = False
    ) -> str:
        """
        格式化个人完整账单（图片样式）
        
        Args:
            deposits: 用户入款记录列表
            withdraws: 用户下发记录列表
            summary: 用户汇总数据字典
            group_name: 群组名称
            user_name: 用户名称
            currency: 币种
            group_exchange_rate: 群组汇率（优先使用）
            group_fee_rate: 群组费率（优先使用）
            display_mode: 显示模式 (pure/reply/operator)
        """
        lines = []
        if show_member_name:
            display_mode = "reply"
        
        # 辅助函数：构建消息链接
        def build_message_link(trans):
            chat_id_str = str(trans.group_id)
            if chat_id_str.startswith("-100"):
                chat_id_for_link = chat_id_str[4:]
            else:
                chat_id_for_link = chat_id_str.replace("-", "")
            target_id = trans.reply_to_message_id or trans.message_id
            if target_id:
                return f"https://t.me/c/{chat_id_for_link}/{target_id}"
            return None
        
        # 辅助函数：格式化带链接的蓝色金额（HTML格式）
        # 注意：Telegram不支持自定义颜色的<span>，使用粗体替代
        def format_amount_link_blue(amount_str, trans):
            link = build_message_link(trans)
            if link:
                # 使用HTML格式，粗体 + 可点击链接（Telegram不支持自定义颜色）
                return f'<a href="{link}"><b>{amount_str}</b></a>'
            return f'<b>{amount_str}</b>'
        
        # 辅助函数：格式化纯蓝色金额（无链接，用于汇总）
        # 注意：Telegram不支持自定义颜色的<span>，使用粗体替代
        def format_amount_blue(amount_str):
            return f'<b>{amount_str}</b>'
        
        # 标题
        lines.append(f"{group_name}")
        lines.append(f"{user_name} 今日个人记账汇总：")
        lines.append("")
        
        # 入款部分
        deposit_count = summary.get('deposit_count', len(deposits))
        displayed_deposit_count = len(deposits)
        lines.append(f"<b>今日入款（{displayed_deposit_count}笔）</b>")
        
        if deposits:
            for trans in deposits:
                # 时间：使用消息发送时间（转换为北京时间）
                time_str = Formatter._format_time_to_beijing(trans.message_date or trans.transaction_date)
                
                # 金额计算 - 优先使用人民币金额（cny_amount）
                amount = trans.cny_amount if trans.cny_amount and trans.cny_amount > 0 else trans.amount
                # 修复：优先使用交易记录保存的汇率，而不是群组当前汇率
                # 这样设置汇率后，历史入账不会被影响
                exchange_rate = trans.exchange_rate or group_exchange_rate or 1
                
                # 根据群组currency显示格式
                if currency == "USDT":
                    # ✅ 修复：使用扣费后的金额计算 USDT，确保显示与计算一致
                    # 格式：15:36 5000 * 0.70 / 50 = 70.00U
                    final_amount = trans.final_amount or amount  # 扣费后金额
                    usdt_amount = final_amount / exchange_rate
                    # 根据display_mode决定显示内容
                    if display_mode == "pure":
                        person_str = ""
                    else:
                        # 非纯净模式：显示操作人，点击跳转到操作消息
                        operator_name = trans.operator_first_name or trans.operator_username or f"用户{trans.operator_id}"
                        
                        # ✅ 构建操作人消息链接（优先使用 operator_chat_id + message_id）
                        if trans.message_id:
                            # 如果有 operator_chat_id，使用它；否则使用 group_id
                            chat_id_for_link = trans.operator_chat_id if hasattr(trans, 'operator_chat_id') and trans.operator_chat_id else trans.group_id
                            chat_id_str = str(chat_id_for_link)
                            if chat_id_str.startswith("-100"):
                                chat_id_for_link = chat_id_str[4:]  # 去掉 "-100" 前缀
                            else:
                                chat_id_for_link = chat_id_str.replace("-", "")
                            message_link = f"https://t.me/c/{chat_id_for_link}/{trans.message_id}"
                        else:
                            # 没有 message_id，使用 tg://user 协议
                            message_link = f"tg://user?id={trans.operator_id}"
                        
                        person_str = f' <a href="{message_link}">{Formatter.escape_html(operator_name)}</a>'
                    
                    # ✅ 新格式：时间 金额*费率/汇率=USDT
                    fee_rate = trans.fee_rate or group_fee_rate or 0
                    fee_multiplier = (100 - fee_rate) / 100 if fee_rate > 0 else 1.0
                    
                    # 根据数值大小决定小数位数，金额直接显示（不加链接和蓝色高亮）
                    amount_display = f"{amount:.0f}"
                    
                    if fee_rate > 0:
                        # 有费率：显示 时间 金额*费率系数/汇率=USDT
                        line = f"{time_str}  {amount_display}*{fee_multiplier:.1f} / {exchange_rate:.0f}={usdt_amount:.2f}"
                        lines.append(line)
                    else:
                        # 无费率：显示 时间 金额/汇率=USDT
                        line = f"{time_str}  {amount_display} / {exchange_rate:.0f}={usdt_amount:.2f}"
                        lines.append(line)
                else:
                    # 根据display_mode决定显示内容
                    if display_mode == "pure":
                        person_str = ""
                    elif display_mode == "reply":
                        # reply 模式：显示被记账的人（reply to 的人）
                        person_name = trans.first_name or trans.username or f"用户{trans.user_id}"
                        person_str = f' <a href="tg://user?id={trans.user_id}">{Formatter.escape_html(person_name)}</a>'
                    else:
                        # operator 模式：显示操作人，点击跳转到操作消息
                        operator_name = trans.operator_first_name or trans.operator_username or f"用户{trans.operator_id}"
                        
                        # ✅ 构建操作人消息链接（优先使用 operator_chat_id + message_id）
                        if trans.message_id:
                            # 如果有 operator_chat_id，使用它；否则使用 group_id
                            chat_id_for_link = trans.operator_chat_id if hasattr(trans, 'operator_chat_id') and trans.operator_chat_id else trans.group_id
                            chat_id_str = str(chat_id_for_link)
                            if chat_id_str.startswith("-100"):
                                chat_id_for_link = chat_id_str[4:]  # 去掉 "-100" 前缀
                            else:
                                chat_id_for_link = chat_id_str.replace("-", "")
                            message_link = f"https://t.me/c/{chat_id_for_link}/{trans.message_id}"
                        else:
                            # 没有 message_id，使用 tg://user 协议
                            message_link = f"tg://user?id={trans.operator_id}"
                        
                        person_str = f' <a href="{message_link}">{Formatter.escape_html(operator_name)}</a>'
                    amount_display = f"¥{amount:.2f}"
                    lines.append(f"{time_str} {amount_display}{person_str}")
        else:
            lines.append("无入款记录")
        
        # 下发部分
        # 🌟 修复：使用summary中的总下发笔数，而不是limit后的列表长度
        withdraw_count = summary.get('withdraw_count', len(withdraws))
        displayed_withdraw_count = len(withdraws)
        lines.append(f"\n<b>今日下发（{displayed_withdraw_count}笔）</b>")
        
        if withdraws:
            for trans in withdraws:
                # 时间：使用消息发送时间（转换为北京时间）
                time_str = Formatter._format_time_to_beijing(trans.message_date or trans.transaction_date)
                
                # 根据群组currency显示格式
                if currency == "USDT":
                    # ✅ 修复：下发记录显示格式 - USDT金额(CNY金额) 操作人
                    # USDT金额（用户输入的金额，直接使用 trans.amount）
                    usdt_amount = trans.amount
                    # CNY金额（下发的人民币金额）
                    cny_amount = trans.cny_amount if trans.cny_amount and trans.cny_amount > 0 else trans.amount
                    
                    # ✅ BUG-1 修复：在使用 person_str 之前先定义它
                    if display_mode == "pure":
                        person_str = ""
                    elif display_mode == "reply":
                        # reply 模式：显示被记账的人（reply to 的人）
                        person_name = trans.first_name or trans.username or f"用户{trans.user_id}"
                        person_str = f' <a href="tg://user?id={trans.user_id}">{Formatter.escape_html(person_name)}</a>'
                    else:
                        # operator 模式：显示操作人，点击跳转到操作消息
                        operator_name = trans.operator_first_name or trans.operator_username or f"用户{trans.operator_id}"
                        
                        # ✅ 构建操作人消息链接（优先使用 operator_chat_id + message_id）
                        if trans.message_id:
                            # 如果有 operator_chat_id，使用它；否则使用 group_id
                            chat_id = trans.operator_chat_id or group_id
                            chat_id_str = str(chat_id)
                            if chat_id_str.startswith("-100"):
                                chat_id_for_link = chat_id_str[4:]  # 去掉 "-100" 前缀
                            else:
                                chat_id_for_link = chat_id_str.replace("-", "")
                            operator_link = f"https://t.me/c/{chat_id_for_link}/{trans.message_id}"
                            person_str = f" <a href=\"{operator_link}\">{Formatter.escape_html(operator_name)}</a>"
                        else:
                            person_str = f" {Formatter.escape_html(operator_name)}"
                    
                    # 显示格式：时间 USDT金额(CNY金额) 操作人
                    if usdt_amount == int(usdt_amount):
                        usdt_display = f"{usdt_amount:.0f}U"
                    elif usdt_amount * 10 == int(usdt_amount * 10):
                        usdt_display = f"{usdt_amount:.1f}U"
                    else:
                        usdt_display = f"{usdt_amount:.2f}U"
                    
                    if cny_amount == int(cny_amount):
                        cny_display = f"{cny_amount:.0f}"
                    elif cny_amount * 10 == int(cny_amount * 10):
                        cny_display = f"{cny_amount:.1f}"
                    else:
                        cny_display = f"{cny_amount:.2f}"
                    
                    lines.append(f"{time_str} {usdt_display}({cny_display}){person_str}")
                else:
                    # 根据display_mode决定显示内容
                    if display_mode == "pure":
                        person_str = ""
                    elif display_mode == "reply":
                        # reply 模式：显示被记账的人（reply to 的人）
                        person_name = trans.first_name or trans.username or f"用户{trans.user_id}"
                        person_str = f' <a href="tg://user?id={trans.user_id}">{Formatter.escape_html(person_name)}</a>'
                    else:
                        # operator 模式：显示操作人，点击跳转到操作消息
                        operator_name = trans.operator_first_name or trans.operator_username or f"用户{trans.operator_id}"
                        
                        # ✅ 构建操作人消息链接（优先使用 operator_chat_id + message_id）
                        if trans.message_id:
                            # 如果有 operator_chat_id，使用它；否则使用 group_id
                            chat_id_for_link = trans.operator_chat_id if hasattr(trans, 'operator_chat_id') and trans.operator_chat_id else trans.group_id
                            chat_id_str = str(chat_id_for_link)
                            if chat_id_str.startswith("-100"):
                                chat_id_for_link = chat_id_str[4:]  # 去掉 "-100" 前缀
                            else:
                                chat_id_for_link = chat_id_str.replace("-", "")
                            message_link = f"https://t.me/c/{chat_id_for_link}/{trans.message_id}"
                        else:
                            # 没有 message_id，使用 tg://user 协议
                            message_link = f"tg://user?id={trans.operator_id}"
                        
                        person_str = f' <a href="{message_link}">{Formatter.escape_html(operator_name)}</a>'
                    amount_display = format_amount_link_blue(f"¥{trans.amount:.2f}", trans)
                    lines.append(f"{time_str} {amount_display}{person_str}")
        else:
            lines.append("暂无下发")
        
        lines.append("")
        
        # 汇总信息
        total_deposit = summary.get('deposit_cny', 0)  # ✅ CNY总额（用于显示和计算未下发）
        deposit_cny = summary.get('deposit_cny', 0)  # ✅ 使用已固化的CNY金额
        exchange_rate = group_exchange_rate or summary.get('exchange_rate', 0)
        fee_rate = group_fee_rate or summary.get('fee_rate', 0)
        
        if currency == "USDT":
            # ✅ 核心理念：汇率只在入账时使用一次，汇总时零计算！
            # 汇总时直接使用数据库中已冻结的 amount_usd 和 fee_amount_usd
            pass
        else:
            # ✅ 删除重复输出，完整汇总在后面统一显示
            pass
        
        # 显示当前设置的汇率和费率
        if currency == "USDT":
            # USDT 账单：汇率已在入账时冻结，汇总区显示“已冻结”
            lines.append("汇率：已冻结（逐笔记录）")
            if fee_rate:
                lines.append(f"费率：{fee_rate}%")
            lines.append("")
        else:
            # CNY 账单：显示当前汇率和费率
            if exchange_rate:
                if exchange_rate == int(exchange_rate):
                    lines.append(f"汇率：{exchange_rate:.0f}")
                elif exchange_rate * 10 == int(exchange_rate * 10):
                    lines.append(f"汇率：{exchange_rate:.1f}")
                else:
                    lines.append(f"汇率：{exchange_rate:.2f}")
            if fee_rate:
                lines.append(f"费率：{fee_rate}%")
            lines.append("")
        
        # 统计信息
        total_withdraw = summary.get('withdraw_amount', 0)
        withdraw_cny = summary.get('withdraw_cny', 0)  # ✅ 使用已固化的CNY金额
        total_fee = summary.get('total_fee', 0)
        
        # ✅ 修复：应下发是固定的（总入款扣除费率），不受下发影响
        if fee_rate > 0:
            fee_multiplier = (100 - fee_rate) / 100
            # 应下发 = 总入款 * 费率系数（这是固定的）
            should_issue_cny = deposit_cny * fee_multiplier
            # 未下发 = 应下发 - 已下发（这个会变化）
            unissued_cny_calc = should_issue_cny - withdraw_cny
            balance = unissued_cny_calc
        else:
            # 应下发 = 总入款（无费率时）
            should_issue_cny = deposit_cny
            # 未下发 = 应下发 - 已下发
            unissued_cny_calc = should_issue_cny - withdraw_cny
            balance = unissued_cny_calc
        
        # ✅ 未下发 = 总入款 - 总下发（不扣除费率）
        unissued_cny = total_deposit - withdraw_cny
        
        if currency == "USDT":
            # ✅ 核心修复：汇总时直接使用数据库中已冻结的USDT值，零计算！
            # amount_usd = 原始金额USDT(未扣费)
            # final_amount_usd = 扣费后USDT(应下发)
            # fee_amount_usd = 手续费USDT
            
            # 总入款 USDT（未扣费）= SUM(amount_usd)
            usdt_total_deposit_raw = sum(t.amount_usd or 0 for t in deposits)
            
            # 总入款 USDT（扣费后）= SUM(final_amount_usd)
            usdt_total_deposit_final = sum(t.final_amount_usd or 0 for t in deposits)
            
            # 总下发 USDT = SUM(amount_usd)
            usdt_total_withdraw = sum(t.amount_usd or 0 for t in withdraws)
            
            # 手续费 USDT = SUM(fee_amount_usd)
            usdt_fee = sum(t.fee_amount_usd or 0 for t in deposits)
            
            # 应下发 = 总入款USDT(扣费后) → 这是固定的，不受下发影响
            usdt_should_issue = usdt_total_deposit_final
            
            # 未下发 USDT = 应下发USDT - 已下发USDT
            usdt_unissued = usdt_should_issue - usdt_total_withdraw
            
            # 总结余 = 未下发（同义词）
            usdt_balance = usdt_unissued
            
            lines.append(f"总入款：<b>{total_deposit:.0f}</b> ({usdt_total_deposit_final:.2f}U)")
            lines.append(f"总下发：{withdraw_cny:.0f} ({usdt_total_withdraw:.2f}U)")
            lines.append(f"未下发：{unissued_cny:.0f} ({usdt_unissued:.2f}U)")
            lines.append(f"应扣费：{usdt_fee:.2f}U")
            lines.append(f"应下发：{usdt_should_issue:.2f}U")
            lines.append(f"总结余：{usdt_balance:.2f}U")
        else:
            lines.append(f"总入款：<b>¥{total_deposit:.2f}</b>")
            lines.append(f"总下发：¥{total_withdraw:.2f}")
            lines.append(f"应下发：¥{should_issue_cny:.2f}")
            lines.append(f"已下发：¥{withdraw_cny:.2f}")
            lines.append(f"未下发：¥{unissued_cny_calc:.2f}")
            lines.append(f"应扣费：¥{total_fee:.2f}")
            lines.append(f"总结余：¥{balance:.2f}")
        
        return "\n".join(lines)

    @staticmethod
    def format_complete_bill(
        deposits: List,
        withdraws: List,
        summary: dict,
        group_name: str = "记账机器人",
        currency: str = "USDT",
        group_exchange_rate: float = None,
        group_fee_rate: float = None,
        display_mode: str = "pure",
        buttons: List = None,
        deposit_show_name: bool = None,
        withdraw_show_name: bool = None,
        show_member_name: bool = False
    ) -> str:
        """
        格式化完整账单（图片样式）
        
        Args:
            deposits: 入款记录列表
            withdraws: 下发记录列表
            summary: 汇总数据字典
            group_name: 群组名称
            currency: 币种
            group_exchange_rate: 群组汇率（优先使用）
            group_fee_rate: 群组费率（优先使用）
            display_mode: 显示模式 (pure/reply/operator)
            buttons: 自定义按钮列表
            deposit_show_name: 全局配置-入款是否显示名字（True时覆盖display_mode）
            withdraw_show_name: 全局配置-下发是否显示名字（True时覆盖display_mode）
        """
        lines = []
        
        # 辅助函数：构建消息链接
        def build_message_link(trans):
            chat_id_str = str(trans.group_id)
            if chat_id_str.startswith("-100"):
                chat_id_for_link = chat_id_str[4:]
            else:
                chat_id_for_link = chat_id_str.replace("-", "")
            # 优先使用回复的消息ID，否则使用操作消息ID
            target_id = trans.reply_to_message_id or trans.message_id
            if target_id:
                return f"https://t.me/c/{chat_id_for_link}/{target_id}"
            return None
        
        # 辅助函数：格式化带链接的金额
        def format_amount_link(amount_str, trans):
            link = build_message_link(trans)
            if link:
                return f"[{amount_str}]({link})"
            return amount_str
        
        # 辅助函数：格式化带链接的蓝色金额（HTML格式）
        # 注意：Telegram不支持自定义颜色的<span>，使用粗体替代
        def format_amount_link_blue(amount_str, trans):
            link = build_message_link(trans)
            if link:
                # 使用HTML格式，粗体 + 可点击链接（Telegram不支持自定义颜色）
                return f'<a href="{link}"><b>{amount_str}</b></a>'
            return f'<b>{amount_str}</b>'
        
        # 辅助函数：格式化纯蓝色金额（无链接，用于汇总）
        # 注意：Telegram不支持自定义颜色的<span>，使用粗体替代
        def format_amount_blue(amount_str):
            return f'<b>{amount_str}</b>'
        
        # 入款部分（不显示群组名称）
        # 🌟 修复：使用summary中的总入款笔数，而不是limit后的列表长度
        deposit_count = summary.get('deposit_count', len(deposits))
        lines.append(f"<b>今日入款（{deposit_count}笔）</b>")
        
        if deposits:
            # ✅ 修复问题2：反转列表，使最近的交易显示在最下面
            for trans in reversed(deposits):
                # 时间：使用消息发送时间（转换为北京时间）
                time_str = Formatter._format_time_to_beijing(trans.message_date or trans.transaction_date)
                
                # 金额计算 - 优先使用人民币金额（cny_amount）
                # 如果cny_amount存在且不为0，使用它；否则使用amount
                amount = trans.cny_amount if trans.cny_amount and trans.cny_amount > 0 else trans.amount
                # ✅ 修复：优先使用交易记录自己的汇率和费率，保护历史数据不受新设置影响
                exchange_rate = trans.exchange_rate or group_exchange_rate or 1
                fee_rate = trans.fee_rate or group_fee_rate or 0  # 优先使用交易记录的费率
                
                # 根据群组currency显示格式，而不是单条交易的currency
                if currency == "USDT":
                    # ✅ 修复：动态计算 USDT 金额，确保显示与计算一致
                    # 不再使用数据库中的 final_amount_usd（可能未正确计算）
                    # 动态计算 USDT 金额（扣费后）
                    fee_multiplier = (100 - fee_rate) / 100 if fee_rate > 0 else 1.0
                    usdt_amount = (amount * fee_multiplier) / exchange_rate
                    
                    # 📝 显示格式：展示计算过程（使用交易当时的汇率和费率）
                    # amount 是人民币金额，exchange_rate 是交易当时的汇率
                    
                    # 根据display_mode和全局配置决定显示内容
                    if show_member_name or deposit_show_name is True:
                        # 全局开启入款显示名字：显示被记账的人
                        person_name = trans.first_name or trans.username or f"用户{trans.user_id}"
                        person_str = f' <a href="tg://user?id={trans.user_id}">{Formatter.escape_html(person_name)}</a>'
                    elif display_mode == "pure":
                        person_str = ""
                    elif display_mode == "reply":
                        # reply 模式：显示被记账的人（reply to 的人）
                        person_name = trans.first_name or trans.username or f"用户{trans.user_id}"
                        person_str = f' <a href="tg://user?id={trans.user_id}">{Formatter.escape_html(person_name)}</a>'
                    else:
                        # operator 模式：显示操作人，点击跳转到操作消息
                        operator_name = trans.operator_first_name or trans.operator_username or f"用户{trans.operator_id}"
                        
                        # ✅ 构建操作人消息链接（优先使用 operator_chat_id + message_id）
                        if trans.message_id:
                            # 如果有 operator_chat_id，使用它；否则使用 group_id
                            chat_id_for_link = trans.operator_chat_id if hasattr(trans, 'operator_chat_id') and trans.operator_chat_id else trans.group_id
                            chat_id_str = str(chat_id_for_link)
                            if chat_id_str.startswith("-100"):
                                chat_id_for_link = chat_id_str[4:]  # 去掉 "-100" 前缀
                            else:
                                chat_id_for_link = chat_id_str.replace("-", "")
                            message_link = f"https://t.me/c/{chat_id_for_link}/{trans.message_id}"
                        else:
                            # 没有 message_id，使用 tg://user 协议
                            message_link = f"tg://user?id={trans.operator_id}"
                        
                        person_str = f' <a href="{message_link}">{Formatter.escape_html(operator_name)}</a>'
                    
                    # 金额直接显示（不加链接和蓝色高亮）
                    amount_display = f"{amount:.0f}"
                    
                    # 根据费率决定显示格式
                    if fee_rate > 0:
                        # 有费率时：金额 * 费率 / 汇率 = USDT金额
                        # 费率转换为小数（7% -> 0.93）
                        fee_multiplier = (100 - fee_rate) / 100
                        adjusted_amount = amount * fee_multiplier
                        
                        # 根据数值大小决定小数位数
                        if usdt_amount == int(usdt_amount):
                            lines.append(f"{time_str} {amount_display} * {fee_multiplier:.2f} / {exchange_rate:.0f} = {usdt_amount:.2f}U{person_str}")
                        elif usdt_amount * 10 == int(usdt_amount * 10):
                            lines.append(f"{time_str} {amount_display} * {fee_multiplier:.2f} / {exchange_rate:.0f} = {usdt_amount:.2f}U{person_str}")
                        else:
                            lines.append(f"{time_str} {amount_display} * {fee_multiplier:.2f} / {exchange_rate:.0f} = {usdt_amount:.2f}U{person_str}")
                    else:
                        # 无费率时：金额 / 汇率 = USDT金额
                        # 根据数值大小决定小数位数
                        if usdt_amount == int(usdt_amount):
                            lines.append(f"{time_str} {amount_display} / {exchange_rate:.0f} = {usdt_amount:.0f}U{person_str}")
                        elif usdt_amount * 10 == int(usdt_amount * 10):
                            # 一位小数
                            lines.append(f"{time_str} {amount_display} / {exchange_rate:.0f} = {usdt_amount:.1f}U{person_str}")
                        else:
                            # 两位小数
                            lines.append(f"{time_str} {amount_display} / {exchange_rate:.0f} = {usdt_amount:.2f}U{person_str}")
                else:
                    # 根据display_mode和全局配置决定显示内容
                    if show_member_name or deposit_show_name is True:
                        # 全局开启入款显示名字：显示被记账的人
                        person_name = trans.first_name or trans.username or f"用户{trans.user_id}"
                        person_str = f' <a href="tg://user?id={trans.user_id}">{Formatter.escape_html(person_name)}</a>'
                    elif display_mode == "pure":
                        person_str = ""
                    else:
                        # 非纯净模式：显示操作人，点击跳转到操作消息
                        operator_name = trans.operator_first_name or trans.operator_username or f"用户{trans.operator_id}"
                        
                        # ✅ 构建操作人消息链接（优先使用 operator_chat_id + message_id）
                        if trans.message_id:
                            # 如果有 operator_chat_id，使用它；否则使用 group_id
                            chat_id_for_link = trans.operator_chat_id if hasattr(trans, 'operator_chat_id') and trans.operator_chat_id else trans.group_id
                            chat_id_str = str(chat_id_for_link)
                            if chat_id_str.startswith("-100"):
                                chat_id_for_link = chat_id_str[4:]  # 去掉 "-100" 前缀
                            else:
                                chat_id_for_link = chat_id_str.replace("-", "")
                            message_link = f"https://t.me/c/{chat_id_for_link}/{trans.message_id}"
                        else:
                            # 没有 message_id，使用 tg://user 协议
                            message_link = f"tg://user?id={trans.operator_id}"
                        
                        person_str = f' <a href="{message_link}">{Formatter.escape_html(operator_name)}</a>'
                    amount_display = f"¥{amount:.2f}"
                    lines.append(f"{time_str} {amount_display}{person_str}")
        else:
            lines.append("无入款记录")
        
        # 下发部分
        # 🌟 修复：使用summary中的总下发笔数，而不是limit后的列表长度
        withdraw_count = summary.get('withdraw_count', len(withdraws))
        displayed_withdraw_count = len(withdraws)
        lines.append(f"\n<b>今日下发（{displayed_withdraw_count}笔）</b>")
        
        if withdraws:
            # ✅ 修复问题2：反转列表，使最近的交易显示在最下面
            for trans in reversed(withdraws):
                # 时间：使用消息发送时间（转换为北京时间）
                time_str = Formatter._format_time_to_beijing(trans.message_date or trans.transaction_date)
                
                # 根据群组currency显示格式
                if currency == "USDT":
                    # ✅ 修复：下发记录显示格式 - USDT金额(CNY金额) 操作人
                    # 获取CNY金额（下发的人民币金额）
                    cny_amount = trans.cny_amount if trans.cny_amount and trans.cny_amount > 0 else trans.amount
                    # USDT金额（用户输入的金额）
                    usdt_amount = trans.amount
                    
                    # ✅ BUG-1 修复：在使用 person_str 之前先定义它
                    if show_member_name or withdraw_show_name is True:
                        # 全局开启下发显示名字：显示操作人
                        operator_name = trans.operator_first_name or trans.operator_username or f"用户{trans.operator_id}"
                        if trans.message_id:
                            chat_id = trans.operator_chat_id or group_id
                            chat_id_str = str(chat_id)
                            if chat_id_str.startswith("-100"):
                                chat_id_for_link = chat_id_str[4:]
                            else:
                                chat_id_for_link = chat_id_str.replace("-", "")
                            operator_link = f"https://t.me/c/{chat_id_for_link}/{trans.message_id}"
                            person_str = f" <a href=\"{operator_link}\">{Formatter.escape_html(operator_name)}</a>"
                        else:
                            person_str = f" {Formatter.escape_html(operator_name)}"
                    elif display_mode == "pure":
                        person_str = ""
                    else:
                        # 非纯净模式：显示操作人，点击跳转到操作消息
                        operator_name = trans.operator_first_name or trans.operator_username or f"用户{trans.operator_id}"
                        
                        # ✅ 构建操作人消息链接（优先使用 operator_chat_id + message_id）
                        if trans.message_id:
                            # 如果有 operator_chat_id，使用它；否则使用 group_id
                            chat_id = trans.operator_chat_id or group_id
                            chat_id_str = str(chat_id)
                            if chat_id_str.startswith("-100"):
                                chat_id_for_link = chat_id_str[4:]  # 去掉 "-100" 前缀
                            else:
                                chat_id_for_link = chat_id_str.replace("-", "")
                            operator_link = f"https://t.me/c/{chat_id_for_link}/{trans.message_id}"
                            person_str = f" <a href=\"{operator_link}\">{Formatter.escape_html(operator_name)}</a>"
                        else:
                            person_str = f" {Formatter.escape_html(operator_name)}"
                    
                    # 显示格式：时间 USDT金额(CNY金额) 操作人
                    if usdt_amount == int(usdt_amount):
                        usdt_display = f"{usdt_amount:.0f}U"
                    elif usdt_amount * 10 == int(usdt_amount * 10):
                        usdt_display = f"{usdt_amount:.1f}U"
                    else:
                        usdt_display = f"{usdt_amount:.2f}U"
                    
                    if cny_amount == int(cny_amount):
                        cny_display = f"{cny_amount:.0f}"
                    elif cny_amount * 10 == int(cny_amount * 10):
                        cny_display = f"{cny_amount:.1f}"
                    else:
                        cny_display = f"{cny_amount:.2f}"
                    
                    lines.append(f"{time_str} {usdt_display}({cny_display}){person_str}")
                else:
                    # 根据display_mode和全局配置决定显示内容
                    if show_member_name or withdraw_show_name is True:
                        # 全局开启下发显示名字：显示操作人
                        operator_name = trans.operator_first_name or trans.operator_username or f"用户{trans.operator_id}"
                        if trans.message_id:
                            chat_id_for_link = trans.operator_chat_id if hasattr(trans, 'operator_chat_id') and trans.operator_chat_id else trans.group_id
                            chat_id_str = str(chat_id_for_link)
                            if chat_id_str.startswith("-100"):
                                chat_id_for_link = chat_id_str[4:]
                            else:
                                chat_id_for_link = chat_id_str.replace("-", "")
                            message_link = f"https://t.me/c/{chat_id_for_link}/{trans.message_id}"
                            person_str = f' <a href="{message_link}">{Formatter.escape_html(operator_name)}</a>'
                        else:
                            person_str = f" {Formatter.escape_html(operator_name)}"
                    elif display_mode == "pure":
                        person_str = ""
                    else:
                        # 非纯净模式：显示操作人，点击跳转到操作消息
                        operator_name = trans.operator_first_name or trans.operator_username or f"用户{trans.operator_id}"
                        
                        # ✅ 构建操作人消息链接（优先使用 operator_chat_id + message_id）
                        if trans.message_id:
                            # 如果有 operator_chat_id，使用它；否则使用 group_id
                            chat_id_for_link = trans.operator_chat_id if hasattr(trans, 'operator_chat_id') and trans.operator_chat_id else trans.group_id
                            chat_id_str = str(chat_id_for_link)
                            if chat_id_str.startswith("-100"):
                                chat_id_for_link = chat_id_str[4:]  # 去掉 "-100" 前缀
                            else:
                                chat_id_for_link = chat_id_str.replace("-", "")
                            message_link = f"https://t.me/c/{chat_id_for_link}/{trans.message_id}"
                        else:
                            # 没有 message_id，使用 tg://user 协议
                            message_link = f"tg://user?id={trans.operator_id}"
                        
                        person_str = f' <a href="{message_link}">{Formatter.escape_html(operator_name)}</a>'
                    amount_display = format_amount_link_blue(f"¥{trans.amount:.2f}", trans)
                    lines.append(f"{time_str} {amount_display}{person_str}")
        else:
            lines.append("暂无下发")
        
        # ✅ 修复问题1：下发和总入款之间加空行
        lines.append("")
        
        # 汇总信息
        total_deposit = summary.get('deposit_cny', 0)  # 🌟 使用CNY金额
        deposit_cny = summary.get('deposit_cny', 0)  # ✅ 使用已固化的CNY金额
        exchange_rate = group_exchange_rate or summary.get('exchange_rate', 1)
        total_withdraw = summary.get('withdraw_cny', 0)  # 🌟 使用CNY金额
        withdraw_cny = summary.get('withdraw_cny', 0)  # ✅ 使用已固化的CNY金额
        total_fee = summary.get('total_fee', 0)
        fee_rate = group_fee_rate or summary.get('fee_rate', 0)
        
        # ✅ 修复：直接使用汇总中的CNY金额
        total_deposit_cny = summary.get('deposit_cny', 0)
        total_withdraw_cny = summary.get('withdraw_cny', 0)
        total_fee_cny = summary.get('total_fee', 0)
        
        # ✅ 追求完美：应下发 = 总入款CNY - 总下发CNY - 手续费
        # 注意：手续费只针对入款，下发没有手续费
        deposit_after_fee = total_deposit_cny - total_fee_cny
        withdraw_after_fee = total_withdraw_cny  # 下发不扣手续费
        
        # 应下发 = 入款扣费后 - 下发扣费后
        pending_withdraw = deposit_after_fee - withdraw_after_fee
        # 总结余 = 应下发
        balance = pending_withdraw
        
        # 未下发 = 总入款(CNY) - 总下发(CNY)（不扣除费率）
        unissued_cny = total_deposit_cny - total_withdraw_cny
        
        if currency == "USDT":
            # ✅ 修复：直接使用summary中已冻结的USDT金额
            # 注意：deposit_amount 现在是已扣费后的 USDT 金额（final_amount_usd）
            usdt_total_deposit_after_fee = summary.get('deposit_amount', 0)
            usdt_total_withdraw = summary.get('withdraw_amount', 0)
            
            # 总入款 USDT（未扣费）：已扣费 USDT + 手续费 USDT
            usdt_total_deposit = usdt_total_deposit_after_fee + summary.get('fee_amount_usd', 0)
            
            # ✅ 应下发USDT = 总入款USDT(扣费后) → 这是固定的，不受下发影响
            usdt_should_issue = usdt_total_deposit_after_fee
            
            # 未下发USDT = 应下发USDT - 已下发USDT
            usdt_unissued = usdt_should_issue - usdt_total_withdraw
            usdt_balance = usdt_unissued
            
            # 手续费USDT：使用已冻结的手续费
            usdt_fee = summary.get('fee_amount_usd', 0)
            
            # ✅ 新格式：汇总信息
            lines.append(f"")
            lines.append(f"总入款金额：{total_deposit_cny:.0f}")
            
            if fee_rate > 0:
                lines.append(f"费率：{fee_rate:.2f}%")
            
            lines.append(f"固定汇率：{exchange_rate:.0f}")
            lines.append(f"")
            lines.append(f"应下发：{usdt_should_issue:.1f} | {usdt_should_issue:.2f}U")
            lines.append(f"已下发：{total_withdraw_cny:.0f} | {usdt_total_withdraw:.0f}U")
            lines.append(f"未下发：{usdt_unissued:.1f} | {usdt_unissued:.2f}U")
        else:
            lines.append(f"\n汇总 | 入款: <b>¥{total_deposit:.2f}</b> 下发: ¥{total_withdraw:.2f} 未下发: ¥{pending_withdraw:.2f} 余额: ¥{balance:.2f}")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_bill_with_buttons(
        deposits: List,
        withdraws: List,
        summary: dict,
        group_name: str = "记账机器人",
        currency: str = "USDT",
        group_exchange_rate: float = None,
        group_fee_rate: float = None,
        display_mode: str = "pure",
        buttons: List = None,
        deposit_show_name: bool = None,
        withdraw_show_name: bool = None,
        show_member_name: bool = False
    ) -> tuple:
        """
        格式化完整账单并返回按钮
        
        Returns:
            tuple: (账单文本, 按钮列表)
        """
        # 生成账单文本
        bill_text = Formatter.format_complete_bill(
            deposits=deposits,
            withdraws=withdraws,
            summary=summary,
            group_name=group_name,
            currency=currency,
            group_exchange_rate=group_exchange_rate,
            group_fee_rate=group_fee_rate,
            display_mode=display_mode,
            deposit_show_name=deposit_show_name,
            withdraw_show_name=withdraw_show_name,
            show_member_name=show_member_name,
        )
        
        # 生成按钮
        button_list = []
        if buttons:
            from telegram import InlineKeyboardButton
            
            # ✅ 修复：按sort_order分组，相同行号的按钮放同一行
            # 先过滤掉无效链接
            valid_buttons = [
                btn for btn in buttons 
                if 'localhost' not in btn.button_url and '127.0.0.1' not in btn.button_url
            ]
            
            # 按sort_order分组
            buttons_by_row = {}
            for btn in valid_buttons:
                row_num = btn.sort_order
                if row_num not in buttons_by_row:
                    buttons_by_row[row_num] = []
                buttons_by_row[row_num].append(btn)
            
            # 按行号排序，生成按钮行
            for row_num in sorted(buttons_by_row.keys()):
                row_buttons = buttons_by_row[row_num]
                # 每行最多2个按钮
                row = []
                for btn in row_buttons[:2]:  # 限制每行2个
                    row.append(InlineKeyboardButton(btn.button_text, url=btn.button_url))
                if row:  # 只添加非空的行
                    button_list.append(row)
        
        return bill_text, button_list

    @staticmethod
    def escape_markdown(text: str) -> str:
        """
        转义Markdown特殊字符
        """
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text
