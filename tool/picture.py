"""
通用图片格式工具，与 AstrBot 无关。

判断图片是什么格式（通过文件头魔数识别，比依赖文件扩展名更可靠）。
只依赖标准库，拿到别的项目里也能直接用。

调用示例：
mimeType = detectMimeType(imageBytes)
"""

from __future__ import annotations

# 常见的图片生成 API 能接受这些格式；调用方可用它判断一张图能不能直接传给模型。
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
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):  # GIF 有两个常见版本，但部分生图接口不一定接收
        return "image/gif"
    if len(data) > 12 and data[4:8] == b"ftyp":  # HEIC/HEIF 是 ISO 基础媒体格式，格式名藏在 brand 字段
        brand = data[8:12]
        if brand in (b"heic", b"heix", b"heim", b"heis"):
            return "image/heic"
        if brand in (b"mif1", b"msf1", b"heif"):
            return "image/heif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":  # WEBP 是 RIFF 容器，第 8 到 12 字节写着 WEBP
        return "image/webp"
    return "application/octet-stream"  # 识别不到就返回通用二进制，让调用方自行决定是否跳过
