"""
这个文件放文本相关的通用小工具。

它不知道 AstrBot，也不知道生图业务，只提供脱敏、参数校验和截断展示这类到处都能复用的能力。
"""

from __future__ import annotations

supportedAspectRatios = ("自动", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9")  # 保存这一项数据，后面的流程会继续使用。
supportedResolutions = ("1K", "2K", "4K")  # 保存这一项数据，后面的流程会继续使用。


def maskSensitive(value: str, visibleChars: int = 4, minLength: int = 8) -> str:  # 定义一个可重复调用的小动作。
    """隐藏敏感字符串中间部分；日志里展示用户 ID 和 Key 时使用。"""
    if len(value) <= minLength:  # 先判断这个情况，避免后面流程出错。
        return "****"  # 把结果交回调用者，这就是本步的反馈。
    return f"{value[:visibleChars]}****{value[-visibleChars:]}"  # 把结果交回调用者，这就是本步的反馈。


def validateAspectRatio(value: str | None) -> str | None:  # 定义一个可重复调用的小动作。
    """只允许配置表里声明过的宽高比，避免无效参数传给供应商。"""
    if value is None:  # 先判断这个情况，避免后面流程出错。
        return None  # 把结果交回调用者，这就是本步的反馈。
    return value if value in supportedAspectRatios else None  # 把结果交回调用者，这就是本步的反馈。


def validateResolution(value: str | None) -> str | None:  # 定义一个可重复调用的小动作。
    """只允许 1K、2K、4K 三档分辨率，其他值视为没传。"""
    if value is None:  # 先判断这个情况，避免后面流程出错。
        return None  # 把结果交回调用者，这就是本步的反馈。
    return value if value in supportedResolutions else None  # 把结果交回调用者，这就是本步的反馈。


def shortText(text: str, length: int = 20) -> str:  # 定义一个可重复调用的小动作。
    """把长文本缩短用于列表展示；不会改变真实保存的内容。"""
    return text[:length] + "..." if len(text) > length else text  # 把结果交回调用者，这就是本步的反馈。
