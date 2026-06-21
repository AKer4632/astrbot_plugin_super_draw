"""
图片文件保存和缓存清理工具。

生图接口返回的是原始字节（bytes），这个文件负责把它们存成真正的图片文件，
还负责定期清理旧缓存，防止磁盘被撑爆。

调用示例：
    path = saveImage(cacheDir, imageBytes, "png")         # -> "d:/cache/gen_1234_abc.png"
    path = saveImage(cacheDir, imageBytes, "webp", 85)    # -> 转成 webp 格式，质量 85
    deleted = await cleanCache(cacheDir, maxCount=100)    # -> 删掉最旧的，只保留 100 个文件
"""

from __future__ import annotations

import hashlib
import io
import os
import time
from pathlib import Path
from typing import Literal

# Pillow 是可选依赖：装了就能转格式（webp/jpeg），没装就只能原样保存 png
try:
    from PIL import Image
except ImportError:
    Image = None

# 支持的保存格式
Format = Literal["png", "webp", "jpeg"]


def saveImage(cacheDir: Path, imageBytes: bytes, fmt: Format = "png", quality: int = 90) -> str | None:
    """
    把图片字节保存到缓存目录。
    如果指定了 webp/jpeg 格式且装了 Pillow，会做格式转换；否则原样保存为 png。
    成功返回文件路径字符串，失败返回 None。
    """

    try:
        cacheDir.mkdir(parents=True, exist_ok=True)

        # 用时间戳 + 内容哈希生成文件名，避免重名覆盖
        imageHash = hashlib.md5(imageBytes).hexdigest()[:8]
        fileName = f"gen_{int(time.time())}_{imageHash}.{fmt}"
        filePath = cacheDir / fileName

        # png 格式直接写入，不需要 Pillow
        if fmt == "png":
            filePath.write_bytes(imageBytes)
            return str(filePath)

        # webp/jpeg 格式需要 Pillow 做转换
        if Image is not None:
            img = Image.open(io.BytesIO(imageBytes))
            if img.mode in ("RGBA", "P") and fmt == "jpeg":  # JPEG 不支持透明通道，先转成 RGB
                img = img.convert("RGB")
            saveArgs = {"quality": quality} if fmt in ("jpeg", "webp") else {}
            img.save(filePath, format=fmt.upper(), **saveArgs)
            return str(filePath)

        # Pillow 没装，退回原样保存为 png
        filePath = filePath.with_suffix(".png")
        filePath.write_bytes(imageBytes)
        return str(filePath)

    except Exception:
        return None


async def cleanCache(cacheDir: Path, maxCount: int) -> int:
    """
    清理缓存目录：按修改时间排序，只保留最新的 maxCount 个文件，多余的从最旧开始删。
    返回实际删除的文件数量。
    """

    if not cacheDir.exists():
        return 0

    # 列出所有文件并按修改时间排序（最旧的排前面）
    files = [(p, os.path.getmtime(p)) for p in cacheDir.iterdir() if p.is_file()]
    files.sort(key=lambda item: item[1])

    if len(files) <= maxCount:
        return 0

    # 删掉最旧的，只保留 maxCount 个
    deleted = 0
    for path, _ in files[: len(files) - maxCount]:
        try:
            path.unlink()
            deleted += 1
        except OSError:
            pass

    return deleted
