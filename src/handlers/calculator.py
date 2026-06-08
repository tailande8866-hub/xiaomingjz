"""
计算器处理器 - 处理数学表达式计算
"""
from telegram import Update
from telegram.ext import ContextTypes
import re
import logging
from ..utils.parser import CommandParser

logger = logging.getLogger(__name__)


def safe_calculate(expression: str) -> str:
    """
    安全地计算数学表达式
    
    Args:
        expression: 数学表达式字符串
        
    Returns:
        计算结果或错误信息
    """
    # 清理表达式：去除空格
    expr = expression.strip()
    
    if not expr:
        return "❌ 表达式不能为空"
    
    # 安全检查：只允许数字、运算符、括号、小数点
    if not re.match(r'^[\d\s\+\-\*\/\.\(\)]+$', expr):
        return "❌ 表达式包含非法字符\n\n只支持：数字、+、-、*、/、(、)"
    
    try:
        # 使用 eval 计算（已通过正则表达式限制输入）
        result = eval(expr)
        
        # 格式化结果
        if isinstance(result, float):
            # 如果是整数，去掉小数部分
            if result == int(result):
                return f"计算结果：{int(result)}"
            else:
                # 保留最多8位小数，去掉末尾的0
                formatted = f"{result:.8f}".rstrip('0').rstrip('.')
                return f"计算结果：{formatted}"
        else:
            return f"计算结果：{result}"
            
    except ZeroDivisionError:
        return "❌ 错误：除数不能为零"
    except SyntaxError:
        return "❌ 错误：表达式语法不正确"
    except Exception as e:
        return f"❌ 计算错误：{str(e)}"


async def handle_calculation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理数学表达式计算"""
    if not update.message or not update.effective_chat:
        return

    text = update.message.text.strip()

    # 记账格式优先，普通带数字文本也不应被计算器误处理
    if CommandParser.is_accounting_command(text):
        return
    
    # ✅ 关键修复1：如果用户正在创建Bot，不要拦截Token输入
    creating_bot = context.user_data.get('creating_bot')
    bot_step = context.user_data.get('bot_step')
    logger.debug(f"Calculator handler: text={text[:30]}, creating_bot={creating_bot}, bot_step={bot_step}")
    
    if creating_bot and bot_step == 'waiting_token':
        logger.debug("Skipping calculator: user is waiting for bot token")
        return  # 跳过计算器，让Bot Token输入handler处理
    
    # ✅ 关键修复2：排除Bot Token格式的消息（包含冒号的消息）
    # Bot Token格式：123456789:ABCdef...
    if ':' in text:
        logger.debug(f"Skipping calculator: message contains colon (possible bot token)")
        return  # 可能是Bot Token，不处理
    
    # 只允许纯数学表达式进入计算器，混杂普通文本时直接忽略
    if CommandParser.is_pure_math_expression(text):
        result = safe_calculate(text)
        await update.message.reply_text(result)
