"""
这个文件放“文件”小工具。

它不懂生图业务，只做两件普通事：保存图片文件、清理太旧的缓存文件。
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from astrbot.api import logger


def saveGeneratedPicture(cacheDir: Path, taskID: str, imageBytes: bytes) -> str | None:  # 定义一个可重复调用的小动作。
    """保存生成好的图片，返回文件路径。"""
    try:  # 尝试执行可能失败的外部操作。
        cacheDir.mkdir(parents=True, exist_ok=True)  # 没有 cache 目录就先创建。
        imageHash = hashlib.md5(imageBytes).hexdigest()[:6]  # 用图片内容做短编号，避免文件名重复。
        filePath = cacheDir / f"gen_{taskID}_{int(time.time())}_{imageHash}.png"  # 文件名里带任务号和时间。
        filePath.write_bytes(imageBytes)  # 把图片字节写进文件。
        return str(filePath)  # AstrBot 发本地图片需要字符串路径。
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[ImageGen] 保存图片失败: {exc}")  # 这一行按当前流程执行，作用见上方说明。
        return None  # 把结果交回调用者，这就是本步的反馈。


async def cleanCache(cacheDir: Path, maxCacheCount: int) -> None:  # 定义一个需要等待网络或文件的异步动作。
    """缓存太多时删除最旧的文件。"""
    if not cacheDir.exists():  # 先判断这个情况，避免后面流程出错。
        return  # 目录不存在说明还没有缓存。

    files = [(path, os.path.getmtime(path)) for path in cacheDir.iterdir() if path.is_file()]  # 记录文件和修改时间。
    files.sort(key=lambda item: item[1])  # 修改时间越早，排得越前。
    if len(files) <= maxCacheCount:  # 先判断这个情况，避免后面流程出错。
        return  # 文件数量没超限制，不需要删除。

    deletedCount = 0  # 记录删了几个，方便日志检查。
    for path, changeTime in files[: len(files) - maxCacheCount]:  # 逐个处理旧缓存；changeTime 只用于排序，删除时不用它。
        try:  # 尝试执行可能失败的外部操作。
            path.unlink()  # 删除旧文件。
            deletedCount += 1  # 保存这一项数据，后面的流程会继续使用。
        except OSError as exc:  # 把异常变成可读的错误或日志，避免插件崩掉。
            logger.debug(f"[ImageGen] 删除缓存文件失败: {path} - {exc}")  # 这一行按当前流程执行，作用见上方说明。
    logger.info(f"[ImageGen] 已清理 {deletedCount} 个旧缓存文件。")  # 这一行按当前流程执行，作用见上方说明。
