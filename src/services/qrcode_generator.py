"""
二维码生成器
"""
import qrcode
from PIL import Image
import os


class QRCodeGenerator:
    """TRC20地址二维码生成器"""
    
    @staticmethod
    def generate_address_qrcode(address: str) -> bytes:
        """
        生成TRC20地址收款二维码（返回字节流）
        
        Args:
            address: TRC20地址
            
        Returns:
            生成的二维码图片字节流（PNG格式）
        """
        # 创建二维码
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(address)
        qr.make(fit=True)
        
        # 生成图片
        img = qr.make_image(fill_color="black", back_color="white")
        
        # 将图片保存到内存缓冲区
        from io import BytesIO
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)  # 重置指针到开头
        
        return buffer.getvalue()
