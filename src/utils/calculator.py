"""
计算工具
"""
from typing import Optional, Dict, Any


class Calculator:
    """金额计算器"""

    @staticmethod
    def calculate_transaction(
        amount: float,
        currency: str = "USDT",
        exchange_rate: Optional[float] = None,
        fee_rate: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        计算交易金额（追求完美：账是记录出来的，不是算出来的）

        Args:
            amount: 原始金额
            currency: 币种 (USDT/CNY)
            exchange_rate: 汇率
            fee_rate: 费率(%)

        Returns:
            {
                'amount': float,  # 原始金额
                'currency': str,
                'cny_amount': float,  # 人民币金额
                'fee_amount': float,  # 手续费
                'final_amount': float,  # 最终金额
                'amount_usd': float,  # ✅ USDT金额(冻结)
                'fee_amount_usd': float  # ✅ 手续费USDT(冻结)
            }
        """
        result = {
            'amount': amount,
            'currency': currency,
            'cny_amount': 0.0,
            'fee_amount': 0.0,
            'final_amount': amount,
            'amount_usd': 0.0,  # ✅ 原始金额USDT(未扣费)
            'final_amount_usd': 0.0,  # ✅ 新增：扣费后USDT金额
            'fee_amount_usd': 0.0  # ✅ 手续费USDT
        }

        # 如果是USDT，需要转换为人民币
        if currency == 'USDT' and exchange_rate:
            result['cny_amount'] = amount * exchange_rate
            base_amount = result['cny_amount']
        else:
            result['cny_amount'] = amount
            base_amount = amount

        # 计算手续费
        if fee_rate:
            result['fee_amount'] = base_amount * (fee_rate / 100)
            result['final_amount'] = base_amount - result['fee_amount']
        else:
            result['final_amount'] = base_amount

        # ✅ 核心修复：入账时冻结 USDT 金额
        # amount_usd = 原始金额 / 汇率 (未扣费)
        # final_amount_usd = 扣费后金额 / 汇率 (应下发)
        # fee_amount_usd = 手续费 / 汇率
        
        if currency == 'USDT':
            result['amount_usd'] = amount  # 原始金额
            result['final_amount_usd'] = result['final_amount']  # 扣费后金额
            result['fee_amount_usd'] = result['fee_amount']  # 手续费
        else:
            # ✅ BUG-7 修复：CNY 转 USDT 时，final_amount_usd 应该存储 USDT 值而非 CNY 值
            # CNY 转 USDT：用冻结的汇率换算
            result['amount_usd'] = result['cny_amount'] / exchange_rate if exchange_rate else 0
            result['final_amount_usd'] = result['final_amount'] / exchange_rate if exchange_rate else 0
            result['fee_amount_usd'] = result['fee_amount'] / exchange_rate if exchange_rate else 0

        # 保留2位小数
        result['cny_amount'] = round(result['cny_amount'], 2)
        result['fee_amount'] = round(result['fee_amount'], 2)
        result['final_amount'] = round(result['final_amount'], 2)
        result['amount_usd'] = round(result['amount_usd'], 2)  # ✅ 原始金额USDT
        result['final_amount_usd'] = round(result['final_amount_usd'], 2)  # ✅ 扣费后USDT
        result['fee_amount_usd'] = round(result['fee_amount_usd'], 2)  # ✅ 手续费USDT

        return result

    @staticmethod
    def evaluate_expression(expression: str) -> Optional[float]:
        """
        安全计算数学表达式
        只支持基本的四则运算
        """
        try:
            # 只允许数字、运算符和括号
            allowed_chars = set('0123456789+-*/.()')
            if not all(c in allowed_chars or c.isspace() for c in expression):
                return None

            # 使用eval计算（已经过滤了危险字符）
            result = eval(expression, {"__builtins__": {}}, {})
            return round(float(result), 2)
        except Exception:
            return None

    @staticmethod
    def format_currency(amount: float, currency: str = "CNY") -> str:
        """
        格式化货币显示
        """
        if currency == "USDT":
            return f"{amount:.2f} USDT"
        else:
            return f"¥{amount:.2f}"

    @staticmethod
    def calculate_summary(transactions: list) -> Dict[str, Any]:
        """
        计算交易汇总

        Args:
            transactions: 交易记录列表

        Returns:
            汇总数据字典
        """
        summary = {
            'deposit_count': 0,
            'deposit_amount': 0.0,
            'deposit_cny': 0.0,
            'withdraw_count': 0,
            'withdraw_amount': 0.0,
            'withdraw_cny': 0.0,
            'storage_amount': 0.0,
            'total_fee': 0.0,
            'fee_amount_usd': 0.0,  # ✅ 新增：冻结的手续费USDT
            'net_amount': 0.0
        }

        for trans in transactions:
            #  BUG-4 修复：使用新的 status 状态机而非 is_deleted
            # 注意：trans.status 是枚举类型，需要转换为字符串或使用枚举值比较
            if trans.status == 'revoked' or trans.status.value == 'revoked' or trans.is_deleted:
                continue

            if trans.transaction_type == 'deposit':
                summary['deposit_count'] += 1
                # ✅ 修复：deposit_amount 应该使用已扣费的 USDT 金额（final_amount_usd）
                # 之前错误地使用了未扣费的 amount_usd，导致汇总时未扣费率
                summary['deposit_amount'] += trans.final_amount_usd or 0  # 已扣费
                summary['deposit_cny'] += trans.cny_amount or 0
                summary['total_fee'] += trans.fee_amount or 0
                # ✅ 只累加入款的手续费（用于计算未扣费总入款）
                summary['fee_amount_usd'] += trans.fee_amount_usd or 0
            elif trans.transaction_type == 'withdraw':
                summary['withdraw_count'] += 1
                # ✅ 追求完美：直接使用冻结的 USDT 金额，零计算
                summary['withdraw_amount'] += trans.amount_usd or 0
                summary['withdraw_cny'] += trans.cny_amount or 0
                summary['total_fee'] += trans.fee_amount or 0
                #  下发手续费不应该影响总入款计算，这里不累加 fee_amount_usd
            elif trans.transaction_type == 'storage':
                summary['storage_amount'] += trans.amount

        summary['net_amount'] = summary['deposit_cny'] - summary['withdraw_cny']
        
        # 保留2位小数
        for key in summary:
            if isinstance(summary[key], float):
                summary[key] = round(summary[key], 2)

        return summary
