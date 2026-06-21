"""
图片格式识别与预处理工具。

通过文件头魔数（前几个字节的固定标记）判断图片格式，
比看文件扩展名更可靠——因为扩展名可以随便改，但文件头骗不了人。

同时提供 normalize_to_supported_image()，把 GIF/动画 WebP 这类
大部分生图接口不支持的动态图转成静态首帧，避免直接传图时报错。

调用示例：
    mime = detectMimeType(imageBytes)       # -> "image/png"
    ok = mime in SUPPORTED_FORMATS          # -> True，说明生图接口能接收这个格式

    data, mime = normalize_to_supported_image(imageBytes)
"""

from __future__ import annotations

import io
from typing import Literal

# Pillow 是可选依赖：tool/file.py 已经用它做格式转换
# 这里复用同一个依赖，保持行为一致
try:
    from PIL import Image
except ImportError:
    Image = None


# 常见生图 API 能直接接收的静态图片格式
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

    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):  # GIF 有两个版本号
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


TargetFormat = Literal["png", "jpeg"]


def normalize_to_supported_image(data: bytes, target_fmt: TargetFormat = "png") -> tuple[bytes, str]):
    """
    把动态图（GIF/动画 WebP）或不支持的格式转成静态首帧。

    如果已经是 SUPPORTED_FORMATS 里的静态格式，直接原样返回。
    如果是 GIF 或 WebP，使用 Pillow seek(0) 取第一帧，再转成 PNG/JPEG bytes。

    Args:
        data: 原始图片字节
        target_fmt: 目标格式，仅支持 "png" 或 "jpeg"

    Returns:
        (处理后的图片字节, MIME 类型字符串)
    """

    mime = detectMimeType(data)

    # 已经是生图接口支持的静态格式，不需要转换
    if mime in SUPPORTED_FORMATS:
        return data, mime

    # Pillow 未安装时无法处理动态图，直接告诉调用方
    if Image is None:
        raise RuntimeError(
            f"检测到图片格式 {mime} 需要 Pillow 提取首帧，但未安装 Pillow。"
            "请在 requirements.txt 中加入 Pillow 后重试。"
        )

    img = Image.open(io.BytesIO(data))

    # 动画格式可能有多个帧，只取第一帧
    try:
        img.seek(0)
    except EOFError:
        pass

    buf = io.BytesIO()

    if target_fmt == "png":
        # PNG 支持透明通道；非 RGB/RGBA 先统一转 RGBA
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        img.save(buf, format="PNG")
        return buf.getvalue(), "image/png"

    # JPEG 目标格式
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    elif img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue(), "image/jpeg"
