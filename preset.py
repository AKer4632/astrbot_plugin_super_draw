"""
这个文件集中处理“预设”这个主体。

预设让用户把一段常用提示词保存成名字，例如 `/预设 添加 手办化:高质量手办照片`。生图时用户写
`/生图 手办化 加一个透明展示盒`，这里会把“手办化”展开成真实提示词，再把追加描述拼到后面。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from .store import ImageStore
from .tool.text import maskSensitive, shortText


@dataclass  # 这一行按当前流程执行，作用见上方说明。
class PresetPrompt:  # 定义一组放在一起的数据或行为。
    """预设解析结果；image.py 会直接拿这些字段生成图片。"""

    prompt: str  # 这一行按当前流程执行，作用见上方说明。
    aspectRatio: str  # 这一行按当前流程执行，作用见上方说明。
    resolution: str  # 这一行按当前流程执行，作用见上方说明。
    matchedName: str | None = None  # 保存这一项数据，后面的流程会继续使用。


def resolvePrompt(store: ImageStore, text: str, aspectRatio: str, resolution: str) -> PresetPrompt:  # 定义一个可重复调用的小动作。
    """把用户输入里的预设名展开；没命中预设就原样返回。"""
    if not text:  # 先判断这个情况，避免后面流程出错。
        return PresetPrompt("", aspectRatio, resolution)  # 把结果交回调用者，这就是本步的反馈。

    firstWord, extraText = splitFirstWord(text)  # 保存这一项数据，后面的流程会继续使用。
    matchedName = findPresetName(store, firstWord)  # 保存这一项数据，后面的流程会继续使用。
    if not matchedName:  # 先判断这个情况，避免后面流程出错。
        return PresetPrompt(text, aspectRatio, resolution)  # 把结果交回调用者，这就是本步的反馈。

    prompt, finalAspectRatio, finalResolution = readPresetContent(store.data.presets[matchedName], aspectRatio, resolution)  # 保存这一项数据，后面的流程会继续使用。
    if extraText:  # 先判断这个情况，避免后面流程出错。
        prompt = f"{prompt} {extraText}"  # 保存这一项数据，后面的流程会继续使用。
    logger.info(f"[ImageGen] 命中预设: {matchedName}")  # 这一行按当前流程执行，作用见上方说明。
    return PresetPrompt(prompt, finalAspectRatio, finalResolution, matchedName)  # 把结果交回调用者，这就是本步的反馈。


async def showOrChange(store: ImageStore, event: AstrMessageEvent):  # 定义一个需要等待网络或文件的异步动作。
    """处理 /预设；无参数展示列表，添加/删除会写回 AstrBot 配置。"""
    messageText = (event.message_str or "").strip()  # 保存这一项数据，后面的流程会继续使用。
    commandText = messageText.split(maxsplit=1)[1].strip() if len(messageText.split(maxsplit=1)) > 1 else ""  # 保存这一项数据，后面的流程会继续使用。
    logger.info(f"[ImageGen] 收到预设指令 - 用户: {maskSensitive(event.unified_msg_origin)}, 内容: {messageText}")  # 这一行按当前流程执行，作用见上方说明。

    if not commandText:  # 先判断这个情况，避免后面流程出错。
        yield event.plain_result(formatPresetList(store))  # 这一行按当前流程执行，作用见上方说明。
        return  # 结束当前流程，不再继续往下走。
    if commandText.startswith("添加 "):  # 先判断这个情况，避免后面流程出错。
        yield event.plain_result(addPreset(store, commandText[3:]))  # 这一行按当前流程执行，作用见上方说明。
        return  # 结束当前流程，不再继续往下走。
    if commandText.startswith("删除 "):  # 先判断这个情况，避免后面流程出错。
        yield event.plain_result(deletePreset(store, commandText[3:]))  # 这一行按当前流程执行，作用见上方说明。
        return  # 结束当前流程，不再继续往下走。
    yield event.plain_result("格式错误：/预设、/预设 添加 名称:内容、/预设 删除 名称")  # 这一行按当前流程执行，作用见上方说明。


def splitFirstWord(text: str) -> tuple[str, str]:  # 定义一个可重复调用的小动作。
    """把第一个词当成可能的预设名，后面整段当追加描述。"""
    parts = text.split(maxsplit=1)  # 保存这一项数据，后面的流程会继续使用。
    return parts[0], parts[1] if len(parts) > 1 else ""  # 把结果交回调用者，这就是本步的反馈。


def findPresetName(store: ImageStore, token: str) -> str | None:  # 定义一个可重复调用的小动作。
    """查找预设名；先精确匹配，再大小写不敏感匹配。"""
    if token in store.data.presets:  # 先判断这个情况，避免后面流程出错。
        return token  # 把结果交回调用者，这就是本步的反馈。
    for name in store.data.presets:  # 逐个处理这组内容，避免漏掉任何一项。
        if name.lower() == token.lower():  # 先判断这个情况，避免后面流程出错。
            return name  # 把结果交回调用者，这就是本步的反馈。
    return None  # 把结果交回调用者，这就是本步的反馈。


def readPresetContent(content: Any, aspectRatio: str, resolution: str) -> tuple[str, str, str]:  # 定义一个可重复调用的小动作。
    """读取普通文本预设或 JSON 预设；兼容 aspect_ratio 和 aspectRatio 两种写法。"""
    if not isinstance(content, str):  # 先判断这个情况，避免后面流程出错。
        return str(content), aspectRatio, resolution  # 把结果交回调用者，这就是本步的反馈。
    if not content.strip().startswith("{"):  # 先判断这个情况，避免后面流程出错。
        return content, aspectRatio, resolution  # 把结果交回调用者，这就是本步的反馈。
    try:  # 尝试执行可能失败的外部操作。
        data = json.loads(content)  # 保存这一项数据，后面的流程会继续使用。
    except json.JSONDecodeError:  # 把异常变成可读的错误或日志，避免插件崩掉。
        return content, aspectRatio, resolution  # 把结果交回调用者，这就是本步的反馈。
    if not isinstance(data, dict):  # 先判断这个情况，避免后面流程出错。
        return content, aspectRatio, resolution  # 把结果交回调用者，这就是本步的反馈。
    return data.get("prompt", ""), data.get("aspectRatio") or data.get("aspect_ratio", aspectRatio), data.get("resolution", resolution)  # 把结果交回调用者，这就是本步的反馈。


def formatPresetList(store: ImageStore) -> str:  # 定义一个可重复调用的小动作。
    """把预设字典格式化成聊天消息。"""
    if not store.data.presets:  # 先判断这个情况，避免后面流程出错。
        return "当前没有预设。"  # 把结果交回调用者，这就是本步的反馈。
    lines = ["预设列表："]  # 保存这一项数据，后面的流程会继续使用。
    for index, (name, prompt) in enumerate(store.data.presets.items(), 1):  # 逐个处理这组内容，避免漏掉任何一项。
        lines.append(f"{index}. {name}: {shortText(str(prompt), 20)}")  # 这一行按当前流程执行，作用见上方说明。
    return "\n".join(lines)  # 把结果交回调用者，这就是本步的反馈。


def addPreset(store: ImageStore, text: str) -> str:  # 定义一个可重复调用的小动作。
    """保存一个预设；格式是“名称:内容”。"""
    if ":" not in text:  # 先判断这个情况，避免后面流程出错。
        return "格式错误：/预设 添加 名称:内容"  # 把结果交回调用者，这就是本步的反馈。
    name, prompt = text.split(":", 1)  # 保存这一项数据，后面的流程会继续使用。
    if not name.strip() or not prompt.strip():  # 先判断这个情况，避免后面流程出错。
        return "格式错误：名称和内容都不能为空。"  # 把结果交回调用者，这就是本步的反馈。
    store.data.savePreset(name.strip(), prompt.strip())  # 这一行按当前流程执行，作用见上方说明。
    return f"预设已添加：{name.strip()}"  # 把结果交回调用者，这就是本步的反馈。


def deletePreset(store: ImageStore, name: str) -> str:  # 定义一个可重复调用的小动作。
    """删除一个预设。"""
    presetName = name.strip()  # 保存这一项数据，后面的流程会继续使用。
    if not presetName:  # 先判断这个情况，避免后面流程出错。
        return "请提供要删除的预设名称。"  # 把结果交回调用者，这就是本步的反馈。
    if store.data.deletePreset(presetName):  # 先判断这个情况，避免后面流程出错。
        return f"预设已删除：{presetName}"  # 把结果交回调用者，这就是本步的反馈。
    return f"预设不存在：{presetName}"  # 把结果交回调用者，这就是本步的反馈。
