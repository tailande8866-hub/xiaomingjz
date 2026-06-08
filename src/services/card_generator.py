"""
TRC20地址卡片图片生成器
"""
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import os
import logging

logger = logging.getLogger(__name__)


class TRC20CardGenerator:
    """TRC20地址验证卡片图片生成器"""
    
    def __init__(self):
        # 颜色配置
        self.BG_COLOR = "#66CCAA"  # 青绿色背景
        self.TITLE_COLOR = "#004433"  # 深绿色标题
        self.SUBTITLE_COLOR = "#006655"  # 副标题
        self.ADDRESS_BG_COLOR = "#006655"  # 地址背景
        self.ADDRESS_TEXT_COLOR = "#FFFFFF"  # 地址文字
        self.TEXT_COLOR = "#004433"  # 普通文字
        
        # 尺寸配置
        self.WIDTH = 800
        self.HEADER_HEIGHT = 320  # 头部区域高度（增加高度以完整显示时间）
        self.PADDING = 40
        
    def generate_card(self, address: str, now_time: str = None) -> bytes:
        """
        生成TRC20地址验证卡片（返回字节流）
        
        Args:
            address: TRC20地址
            now_time: 当前时间字符串
            
        Returns:
            生成的图片字节流（PNG格式）
        """
        if not now_time:
            now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 创建图片
        img = Image.new('RGB', (self.WIDTH, self.HEADER_HEIGHT), color=self.BG_COLOR)
        draw = ImageDraw.Draw(img)
        
        # 尝试加载中文字体
        font_title = self._load_font(60)
        font_subtitle = self._load_font(28)
        font_address = self._load_font(32)
        font_time = self._load_font(36)
        
        # 绘制标题
        title = "USDT防篡改验证核对"
        title_bbox = draw.textbbox((0, 0), title, font=font_title)
        title_width = title_bbox[2] - title_bbox[0]
        title_x = (self.WIDTH - title_width) // 2
        draw.text((title_x, 40), title, fill=self.TITLE_COLOR, font=font_title)
        
        # 绘制副标题
        subtitle = "《请双方谨慎核对地址是否与图中一致,如有误停止付款》"
        subtitle_bbox = draw.textbbox((0, 0), subtitle, font=font_subtitle)
        subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
        subtitle_x = (self.WIDTH - subtitle_width) // 2
        draw.text((subtitle_x, 120), subtitle, fill=self.SUBTITLE_COLOR, font=font_subtitle)
        
        # 绘制地址背景框（圆角矩形）
        address_y = 170
        address_height = 60
        address_padding = 20
        
        # 计算地址文本宽度
        address_bbox = draw.textbbox((0, 0), address, font=font_address)
        address_width = address_bbox[2] - address_bbox[0]
        box_width = address_width + address_padding * 2
        box_x = (self.WIDTH - box_width) // 2
        
        # 绘制圆角矩形
        self._draw_rounded_rect(
            draw,
            (box_x, address_y, box_x + box_width, address_y + address_height),
            radius=15,
            fill=self.ADDRESS_BG_COLOR
        )
        
        # 绘制地址文字
        address_text_x = box_x + address_padding
        address_text_y = address_y + (address_height - 32) // 2
        draw.text((address_text_x, address_text_y), address, fill=self.ADDRESS_TEXT_COLOR, font=font_address)
        
        # 绘制时间（位置上移，确保完整显示）
        time_text = f"Now: {now_time}"
        time_bbox = draw.textbbox((0, 0), time_text, font=font_time)
        time_width = time_bbox[2] - time_bbox[0]
        time_x = (self.WIDTH - time_width) // 2
        draw.text((time_x, 245), time_text, fill=self.TEXT_COLOR, font=font_time)
        
        # 将图片保存到内存缓冲区
        from io import BytesIO
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)  # 重置指针到开头
        
        return buffer.getvalue()
    
    def _draw_rounded_rect(self, draw, bbox, radius, fill):
        """绘制圆角矩形"""
        x0, y0, x1, y1 = bbox
        
        # 绘制矩形主体
        draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
        draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)
        
        # 绘制四个角的扇形（简化为填充）
        # 左上角
        draw.pieslice([x0, y0, x0 + radius * 2, y0 + radius * 2], 180, 270, fill=fill)
        # 右上角
        draw.pieslice([x1 - radius * 2, y0, x1, y0 + radius * 2], 270, 360, fill=fill)
        # 左下角
        draw.pieslice([x0, y1 - radius * 2, x0 + radius * 2, y1], 90, 180, fill=fill)
        # 右下角
        draw.pieslice([x1 - radius * 2, y1 - radius * 2, x1, y1], 0, 90, fill=fill)
    
    def _load_font(self, size):
        """加载字体"""
        # 尝试多种字体路径
        font_paths = [
            # Windows 系统字体
            "C:/Windows/Fonts/msyh.ttc",  # 微软雅黑
            "C:/Windows/Fonts/simhei.ttf",  # 黑体
            "C:/Windows/Fonts/simsun.ttc",  # 宋体
            # Linux/Docker 系统字体（按优先级）
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",  # 文泉驿正黑
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # 文泉驿微米黑
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",  # Droid Sans Fallback
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # DejaVu Sans
            "/usr/share/fonts/TTF/DejaVuSans.ttf",  # Arch Linux
            "/usr/share/fonts/noto/NotoSansCJK-Regular.ttc",  # Noto Sans CJK
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Noto Sans CJK (OpenType)
            # 备用字体
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        
        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    font = ImageFont.truetype(font_path, size)
                    # 测试是否能渲染中文字符
                    test_text = "测试"
                    bbox = font.getbbox(test_text)
                    # 如果能正常渲染（宽度大于0），则使用该字体
                    if bbox[2] - bbox[0] > 0:
                        return font
                except Exception as e:
                    continue
        
        # 如果都失败，使用默认字体（会显示乱码，但不会崩溃）
        logger.warning("⚠️ 未找到合适的中文字体，将使用默认字体（可能显示乱码）")
        return ImageFont.load_default()
