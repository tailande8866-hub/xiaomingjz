"""
帮助中心 HTML 生成器
严格按照用户要求实现
"""
from telegram import Bot

from src.config.help_data import HELP_PAGES


def build_help_page(page: str, bot_name: str = "记账机器人", bot_creator: str = "管理员") -> str:
    """
    生成帮助页面 HTML 内容
    
    格式：
    - 首页：分类列表
    - 分类页：命令列表（可点击复制）
    """
    data = HELP_PAGES.get(page, HELP_PAGES["basic"])
    
    # 首页（分类索引）
    if page == "index":
        lines = []
        lines.append(f"{data['title']}")
        lines.append("")  # 空行
        
        for item in data["content"]:
            if len(item) == 1:
                text = item[0]
                # 替换变量
                text = text.replace("{bot_name}", bot_name)
                text = text.replace("{bot_creator}", bot_creator)
                lines.append(text)
        
        return "\n".join(lines)
    
    # 分类页面
    text = f"{data['title']}\n\n"
    
    for item in data["content"]:
        if len(item) == 2:
            title, command = item
            # 使用 ▫️ 分隔，命令用 <code> 包裹（可点击复制）
            text += f"{title} ▫️ <code>{command}</code>\n"
    
    return text.strip()
