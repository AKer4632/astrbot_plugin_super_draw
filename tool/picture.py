"""
图片格式识别工具。

通过文件头魔数（前几个字节的固定标记）判断图片格式，
比看文件扩展名更可靠——因为扩展名可以随便改，但文件头骗不了人。

调用示例：
    mime = detectMimeType(imageBytes)       # -> "image/png"
    ok = mime in SUPPORTED_FORMATS          # -> True，说明生图接口能接收这个格式
"""

from __future__ import annotations


# 常见生图 API 能接收的图片格式，调用方可以用来判断"这张图能不能直接传给模型"
SUPPORTED_FORMATS = {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}


def detectMimeType(data: bytes) -> str:
    """
    看图片开头的字节判断格式，返回 MIME 类型字符串。
    识别不出来就返回 "application/octet-stream"，让调用方自己决定要不要跳过。
    """

    if data.startswith(b"\xff\xd8"):  # JPEG 固定以 FF D8 开头
        return "image/jpeg"

    if data.startswith(b"\x89PNG\r\n\x1a\n"):  # PNG 有固定 8 字节文件头
        return "image/png"

    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):  # GIF 有两个版本号，部分生图接口不一定接收
        return "image/gif"

    if data.startswith(b"RIFF") and len(data) > 12 and data[8:12] == b"WEBP":  # WEBP 是 RIFF 容器，第 8-12 字节写着 WEBP
        return "image/webp"

    # HEIC/HEIF 是 ISO 基础媒体格式，格式名藏在第 8-12 字节的 brand 字段
    if len(data) > 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"heic", b"heix", b"heim", b"heis"):
            return "image/heic"
        if brand in (b"mif1", b"msf1", b"heif"):
            return "image/heif"

    return "application/octet-stream"  # 兜底：识别不出来就返回通用二进制类型
