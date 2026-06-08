"""
通用文件工具：保存图片、清理缓存。

不依赖 AstrBot，只做两件事：把图片字节写成文件、删除过多的旧缓存。

调用示例：
path = saveImage(cacheDir, imageBytes)
await cleanCache(cacheDir, maxCount=100)
"""

from __future__ import annotations

# 标准库只负责生成文件名、读取文件时间和拼接路径，不包含任何插件业务判断。
import hashlib
import os
import time
from pathlib import Path


def saveImage(cacheDir: Path, imageBytes: bytes) -> str | None:
    """
    保存图片字节到缓存目录，返回文件路径字符串。
    文件名用时间戳+内容哈希，保证不重复。
    失败返回 None。
    """
    try:
        cacheDir.mkdir(parents=True, exist_ok=True)  # 第一次使用缓存目录时自动创建
        imageHash = hashlib.md5(imageBytes).hexdigest()[:8]  # 内容哈希防重名，同一秒多张图也不会互相覆盖
        fileName = f"gen_{int(time.time())}_{imageHash}.png"  # 文件名同时带时间和内容特征，方便人工排查
        filePath = cacheDir / fileName  # 所有生成图集中放进缓存目录，清理时只扫这里
        filePath.write_bytes(imageBytes)  # 真正写入图片字节，AstrBot 后面按路径发送
        return str(filePath)
    except Exception:
        return None


async def cleanCache(cacheDir: Path, maxCount: int) -> int:
    """
    缓存文件超过 maxCount 时删除最旧的，返回删除数量。
    按文件修改时间排序，最旧的先删。
    """
    if not cacheDir.exists():
        return 0

    files = [(path, os.path.getmtime(path)) for path in cacheDir.iterdir() if path.is_file()]  # 只清理文件，不碰子目录
    files.sort(key=lambda item: item[1])  # 修改时间越早排越前，越旧越先删

    if len(files) <= maxCount:
        return 0  # 没超限制，不用删

    # 删除最旧的文件，保留 maxCount 个
    deletedCount = 0
    for path, _ in files[: len(files) - maxCount]:
        try:
            path.unlink()
            deletedCount += 1
        except OSError:
            pass  # 删不掉就跳过，不影响其他文件
    return deletedCount
