"""
这个文件放时间相关的通用小工具。

任务 ID 和每日任务都需要时间，但这些能力本身不属于生图业务，所以放在这里。
"""

from __future__ import annotations

import datetime
import hashlib
import time


def createTaskID(seed: str) -> str:  # 定义一个可重复调用的小动作。
    """用当前时间和一段种子生成 8 位任务 ID；聊天反馈里短一些更好读。"""
    return hashlib.md5(f"{time.time()}{seed}".encode()).hexdigest()[:8]  # 把结果交回调用者，这就是本步的反馈。


def today() -> str:  # 定义一个可重复调用的小动作。
    """返回今天日期，格式固定为 YYYY-MM-DD。"""
    return datetime.date.today().isoformat()  # 把结果交回调用者，这就是本步的反馈。
