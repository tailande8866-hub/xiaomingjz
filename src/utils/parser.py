"""
命令解析工具
"""
import logging
import re
from typing import Optional, Tuple, Dict, Any


logger = logging.getLogger(__name__)


def safe_calculate_expression(expression: str) -> Optional[float]:
    """
    安全地计算数学表达式
    
    Args:
        expression: 数学表达式字符串
        
    Returns:
        计算结果，如果无法计算则返回None
    """
    # 清理表达式：去除空格
    expr = expression.strip()
    
    if not expr:
        return None
    
    # 安全检查：只允许数字、运算符、括号、小数点
    if not re.match(r'^[\d\s\+\-\*\/\.\(\)]+$', expr):
        return None
    
    try:
        # 使用 eval 计算（已通过正则表达式限制输入）
        result = eval(expr)
        
        # 确保结果是数字
        if isinstance(result, (int, float)):
            return float(result)
        else:
            return None
            
    except Exception:
        return None


class CommandParser:
    """命令解析器"""

    # 入款模式
    # ✅ BUG-5 修复：数学表达式现在支持 * / 运算
    # 注意：如果需要使用乘除，请用括号包裹：+(10*5) 或 +((10+20)*3)
    DEPOSIT_PATTERNS = [
        r'^\+([\d\+\-\*\/\.\(\)\s]+)(u)?(?:/([\d\.]+))?(?:\*([\d\.]+)%?)?\s*(.*)$',  # +1000 或 +1000u/7.3*12% 备注
        r'^(.+?)\+([\d\+\-\*\/\.\(\)\s]+)(u)?(?:/([\d\.]+))?(?:\*([\d\.]+)%?)?\s*(.*)$',  # 张三+1000
    ]

    # 下发模式
    # ✅ BUG-5 修复：数学表达式现在支持 * / 运算
    # 支持 r 和 u 两种后缀表示USDT（与入款保持一致）
    WITHDRAW_PATTERNS = [
        r'^下发([\d\+\-\*\/\.\(\)\s]+)(r|u)?(?:/([\d\.]+))?(?:\*([\d\.]+)%?)?\s*(.*)$',  # 下发1000 或 下发10+10 或 下发1000u
        r'^(.+?)下发([\d\+\-\*\/\.\(\)\s]+)(r|u)?(?:/([\d\.]+))?(?:\*([\d\.]+)%?)?\s*(.*)$',  # 张三下发1000 或 张三下发10+10
    ]

    # 寄存模式（已取消 P+ P- 功能）
    STORAGE_PATTERNS = []

    # 修正模式
    CORRECTION_PATTERNS = [
        r'^-(\d+(?:\.\d+)?)\s*(.*)$',  # -1000 (入款修正)
        r'^下发-(\d+(?:\.\d+)?)\s*(.*)$',  # 下发-1000 (下发修正)
    ]

    @staticmethod
    def normalize_accounting_text(text: str) -> str:
        """将现有支持的记账别名归一化为项目内部已使用的格式。"""
        normalized = (text or "").strip()
        if not normalized:
            return ""

        deposit_alias_match = re.match(r'^(入款|上分|收)\s*(.+)$', normalized, re.IGNORECASE)
        if deposit_alias_match:
            return f"+{deposit_alias_match.group(2).strip()}"

        withdraw_alias_match = re.match(r'^(下分|支)\s*(.+)$', normalized, re.IGNORECASE)
        if withdraw_alias_match:
            return f"下发{withdraw_alias_match.group(2).strip()}"

        bare_usdt_match = re.match(r'^(\d+(?:\.\d+)?)([uU])(?:\s+(.*))?$', normalized)
        if bare_usdt_match:
            amount, suffix, note = bare_usdt_match.groups()
            return f"+{amount}{suffix}{(' ' + note.strip()) if note else ''}"

        return normalized

    @staticmethod
    def is_accounting_command(text: str, user_role=None, state=None) -> bool:
        """
        严格判断是否为记账命令。

        仅显式记账格式或明确记账输入状态返回 True。
        """
        normalized = CommandParser.normalize_accounting_text(text)
        if not normalized:
            return False

        if state:
            return True

        if (
            CommandParser.is_pure_math_expression(normalized)
            and not normalized.lstrip().startswith(('+', '-'))
        ):
            return False

        if CommandParser.parse_deposit(normalized):
            return True
        if CommandParser.parse_withdraw(normalized):
            return True
        if CommandParser.parse_correction(normalized):
            return True
        return False

    @staticmethod
    def is_pure_math_expression(text: str) -> bool:
        """仅允许纯数学表达式进入计算器，不接受夹杂普通文本的消息。"""
        expr = (text or "").strip()
        if not expr or ':' in expr:
            return False
        if not re.match(r'^[\d\s\+\-\*\/\.\(\)]+$', expr):
            return False
        return bool(re.search(r'[\+\-\*\/]', expr))

    @staticmethod
    def parse_deposit(text: str) -> Optional[Dict[str, Any]]:
        """
        解析入款命令
        返回: {
            'username': Optional[str],
            'amount': float,
            'currency': str,
            'exchange_rate': Optional[float],
            'fee_rate': Optional[float],
            'note': str
        }
        """
        normalized_text = CommandParser.normalize_accounting_text(text)
        for pattern in CommandParser.DEPOSIT_PATTERNS:
            match = re.match(pattern, normalized_text, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) == 5:  # +1000 格式
                    amount_str, currency_suffix, rate, fee, note = groups
                    # 清理空格
                    amount_str = amount_str.strip()
                    # 尝试计算数学表达式
                    calculated_amount = safe_calculate_expression(amount_str)
                    if calculated_amount is None:
                        # 如果计算失败，尝试直接转换为数字
                        try:
                            calculated_amount = float(amount_str)
                        except ValueError:
                            return None
                    return {
                        'username': None,
                        'amount': calculated_amount,
                        'currency': 'USDT' if currency_suffix and currency_suffix.lower() == 'u' else 'CNY',
                        'exchange_rate': float(rate) if rate else None,
                        'fee_rate': float(fee) if fee else None,
                        'note': note.strip() if note else ''
                    }
                elif len(groups) == 6:  # 张三+1000 格式
                    username, amount_str, currency_suffix, rate, fee, note = groups
                    # 清理空格
                    amount_str = amount_str.strip()
                    # 尝试计算数学表达式
                    calculated_amount = safe_calculate_expression(amount_str)
                    if calculated_amount is None:
                        # 如果计算失败，尝试直接转换为数字
                        try:
                            calculated_amount = float(amount_str)
                        except ValueError:
                            return None
                    return {
                        'username': username.strip(),
                        'amount': calculated_amount,
                        'currency': 'USDT' if currency_suffix and currency_suffix.lower() == 'u' else 'CNY',
                        'exchange_rate': float(rate) if rate else None,
                        'fee_rate': float(fee) if fee else None,
                        'note': note.strip() if note else ''
                    }
        return None

    @staticmethod
    def parse_withdraw(text: str) -> Optional[Dict[str, Any]]:
        """
        解析下发命令
        返回格式同parse_deposit
        """
        try:
            normalized_text = CommandParser.normalize_accounting_text(text)
            for pattern in CommandParser.WITHDRAW_PATTERNS:
                match = re.match(pattern, normalized_text, re.IGNORECASE)
                if match:
                    groups = match.groups()
                    if len(groups) == 5:  # 下发1000 格式
                        amount_str, currency_suffix, rate, fee, note = groups
                        # 尝试计算数学表达式
                        calculated_amount = safe_calculate_expression(amount_str)
                        if calculated_amount is None:
                            calculated_amount = float(amount_str)
                        # ✅ 修复：下发金额永远是USDT,不管带不带后缀
                        return {
                            'username': None,
                            'amount': calculated_amount,
                            'currency': 'USDT',  # 固定为USDT
                            'exchange_rate': float(rate) if rate else None,
                            'fee_rate': float(fee) if fee else None,
                            'note': note.strip() if note else ''
                        }
                    elif len(groups) == 6:  # 张三下发1000 格式
                        username, amount_str, currency_suffix, rate, fee, note = groups
                        # 尝试计算数学表达式
                        calculated_amount = safe_calculate_expression(amount_str)
                        if calculated_amount is None:
                            calculated_amount = float(amount_str)
                        # ✅ 修复：下发金额永远是USDT,不管带不带后缀
                        return {
                            'username': username.strip(),
                            'amount': calculated_amount,
                            'currency': 'USDT',  # 固定为USDT
                            'exchange_rate': float(rate) if rate else None,
                            'fee_rate': float(fee) if fee else None,
                            'note': note.strip() if note else ''
                        }
            return None
        except Exception as e:
            # ✅ BUG-6 修复：添加异常保护，避免解析失败导致整个命令处理崩溃
            logger.error(f"Failed to parse withdraw command: {text}, error: {e}")
            return None

    @staticmethod
    def parse_storage(text: str) -> Optional[Dict[str, Any]]:
        """
        解析寄存命令
        返回: {
            'operation': str,  # '+' or '-'
            'amount': float,
            'note': str
        }
        """
        for pattern in CommandParser.STORAGE_PATTERNS:
            match = re.match(pattern, text.strip(), re.IGNORECASE)
            if match:
                operation, amount, note = match.groups()
                return {
                    'operation': operation,
                    'amount': float(amount),
                    'note': note.strip() if note else ''
                }
        return None

    @staticmethod
    def parse_correction(text: str) -> Optional[Dict[str, Any]]:
        """
        解析修正命令
        返回: {
            'type': str,  # 'deposit' or 'withdraw'
            'amount': float,
            'note': str
        }
        """
        normalized_text = CommandParser.normalize_accounting_text(text)
        for i, pattern in enumerate(CommandParser.CORRECTION_PATTERNS):
            match = re.match(pattern, normalized_text, re.IGNORECASE)
            if match:
                if i == 0:  # 入款修正
                    amount, note = match.groups()
                    return {
                        'type': 'deposit',
                        'amount': float(amount),
                        'note': note.strip() if note else ''
                    }
                elif i == 1:  # 下发修正
                    amount, note = match.groups()
                    return {
                        'type': 'withdraw',
                        'amount': float(amount),
                        'note': note.strip() if note else ''
                    }
        return None

    @staticmethod
    def parse_rate_setting(text: str) -> Optional[Dict[str, Any]]:
        """
        解析汇率/费率设置命令
        设置汇率7.3
        设置费率3
        设置张三汇率7.3
        设置张三费率3
        设置他的汇率7.6
        设置他的费率3
        """
        # 设置汇率
        match = re.match(r'^设置汇率(\d+(?:\.\d+)?)$', text.strip())
        if match:
            return {'type': 'exchange_rate', 'username': None, 'value': float(match.group(1))}

        # 设置费率
        match = re.match(r'^设置费率(\d+(?:\.\d+)?)%?$', text.strip())
        if match:
            return {'type': 'fee_rate', 'username': None, 'value': float(match.group(1))}

        # 设置某人汇率（包括"他的"）
        match = re.match(r'^设置(.+?)汇率(\d+(?:\.\d+)?)$', text.strip())
        if match:
            return {'type': 'exchange_rate', 'username': match.group(1).strip(), 'value': float(match.group(2))}

        # 设置某人费率（包括"他的"）
        match = re.match(r'^设置(.+?)费率(\d+(?:\.\d+)?)%?$', text.strip())
        if match:
            return {'type': 'fee_rate', 'username': match.group(1).strip(), 'value': float(match.group(2))}

        return None

    @staticmethod
    def parse_display_count(text: str) -> Optional[Dict[str, Any]]:
        """
        解析显示条数设置
        设置入款条数5
        设置下发条数5
        """
        match = re.match(r'^设置(入款|下发)条数(\d+)$', text.strip())
        if match:
            trans_type = 'deposit' if match.group(1) == '入款' else 'withdraw'
            return {'type': trans_type, 'count': int(match.group(2))}
        return None

    @staticmethod
    def parse_currency_display(text: str) -> Optional[str]:
        """
        解析币种显示设置
        设置币种AUD
        切换币种USD / 切换币种CNY
        """
        # 设置币种XXX
        match = re.match(r'^设置币种([A-Z]+)$', text.strip())
        if match:
            return match.group(1)
        
        # 切换币种USD/CNY
        match = re.match(r'^切换币种(USD|CNY|usd|cny)$', text.strip(), re.IGNORECASE)
        if match:
            return match.group(1).upper()
        
        return None

    @staticmethod
    def parse_day_cut_time(text: str) -> Optional[str]:
        """
        解析        设置日切时间23:59
        """
        match = re.match(r'^设置日切时间(\d{1,2}):(\d{2})$', text.strip())
        if match:
            hour, minute = match.groups()
            return f"{hour.zfill(2)}:{minute}"
        return None

    @staticmethod
    def is_trc20_address(text: str) -> bool:
        """
        判断是否为TRC20地址
        """
        return bool(re.match(r'^T[A-Za-z0-9]{33}$', text.strip()))
