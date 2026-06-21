"""
通用文件工具：图片保存、格式转换、缓存清理。
"""

from __future__ import annotations

import hashlib
import io
import os
import time
from pathlib import Path
from typing import Literal

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

Format = Literal["png", "webp", "jpeg"]


def saveImage(cacheDir: Path, imageBytes: bytes, fmt: Format = "png", quality: int = 90) -> str | None:
    """保存图片字节到缓存目录，可选格式转换。"""
    try:
        cacheDir.mkdir(parents=True, exist_ok=True)
        ext = fmt.lower()
        imageHash = hashlib.md5(imageBytes).hexdigest()[:8]
        fileName = f"gen_{int(time.time())}_{imageHash}.{ext}"
        filePath = cacheDir / fileName

        if fmt == "png":
            filePath.write_bytes(imageBytes)
        elif Image is not None:
            img = Image.open(io.BytesIO(imageBytes))
            if img.mode in ("RGBA", "P") and fmt == "jpeg":
                img = img.convert("RGB")
            save_kwargs = {"quality": quality} if fmt in ("jpeg", "webp") else {}
            img.save(filePath, format=fmt.upper(), **save_kwargs)
        else:
            # Pillow 没装时回退原样保存
            filePath = filePath.with_suffix(".png")
            filePath.write_bytes(imageBytes)
        return str(filePath)
    except Exception:
        return None


async def cleanCache(cacheDir: Path, maxCount: int) -> int:
    """删除最旧的缓存文件，保留 maxCount 个。"""
    if not cacheDir.exists():
        return 0
    files = [(p, os.path.getmtime(p)) for p in cacheDir.iterdir() if p.is_file()]
    files.sort(key=lambda item: item[1])
    if len(files) <= maxCount:
        return 0
    deleted = 0
    for path, _ in files[: len(files) - maxCount]:
        try:
            path.unlink()
            deleted += 1
        except OSError:
            pass
    return deleted
