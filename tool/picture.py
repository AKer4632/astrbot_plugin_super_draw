"""
通用图片格式工具，与 AstrBot 无关。

判断图片是什么格式，以及在格式不被支持时把图片转成 JPEG。
只依赖 Pillow，拿到别的项目里也能直接用。

调用示例：
mimeType = detectMimeType(imageBytes)
jpegBytes = convertToJPEG(pngBytes)
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image

# 常见的图片生成 API 能接受的格式
supportedFormats = {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}


def detectMimeType(data: bytes) -> str:
    """
    看图片开头的字节判断格式。
    通过文件头魔数识别，比依赖文件扩展名更可靠。
    """
    if data.startswith(b"\xff\xd8"):  # JPEG 以 FF D8 开头
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):  # PNG 有固定 8 字节头
        return "image/png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):  # GIF 两个版本
        return "image/gif"
    if len(data) > 12 and data[4:8] == b"ftyp":  # HEIC/HEIF 是 ISO 基础媒体格式
        brand = data[8:12]
        if brand in (b"heic", b"heix", b"heim", b"heis"):
            return "image/heic"
        if brand in (b"mif1", b"msf1", b"heif"):
            return "image/heif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":  # WEBP 是 RIFF 容器
        return "image/webp"
    return "application/octet-stream"  # 识别不到就返回通用二进制


def convertToJPEG(data: bytes) -> bytes:
    """
    把图片转成 JPEG 格式。
    处理透明通道：RGBA/LA/P 模式先铺白底再转换。
    转换失败时返回原始字节，让 API 自己尝试处理。
    """
    try:
        image = Image.open(BytesIO(data))

        # JPEG 不支持透明通道，需要先铺白底
        if image.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode in ("P", "LA"):
                image = image.convert("RGBA")  # 调色板模式先转 RGBA
            background.paste(image, mask=image.split()[3])  # 用 alpha 通道当遮罩
            image = background

        output = BytesIO()
        image.save(output, format="JPEG", quality=95)  # 95 质量清晰且文件不会太大
        return output.getvalue()
    except Exception:
        return data  # 转换失败就原样返回
