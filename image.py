"""
这个文件写“生图”这一件事。

读代码时按这个顺序看：用户触发 /生图 -> 检查能不能用 -> 读提示词和参考图 -> 后台请求生图接口
-> 保存图片 -> 发回聊天窗口。每个函数都只做这条路上的一小段。
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.core.utils.io import download_image_by_url

from . import preset
from .data import ImageAbility, ImageRequest, PictureData
from .store import ImageStore
from .tool.file import saveGeneratedPicture
from .tool.picture import convertPictures, detectMimeType
from .tool.text import maskSensitive, validateAspectRatio, validateResolution
from .tool.time import createTaskID


async def startFromCommand(store: ImageStore, event: AstrMessageEvent):  # 定义一个需要等待网络或文件的异步动作。
    """用户发 /生图 时从这里开始。"""
    userID = event.unified_msg_origin  # AstrBot 给这次聊天的 ID，用来限速和发回结果。
    checkResult = store.data.checkUserCanGenerate(userID)  # 先看用户是否太频繁或超过每日次数。
    if isinstance(checkResult, str):  # 先判断这个情况，避免后面流程出错。
        yield event.plain_result(checkResult)  # 不允许生图时，把原因直接告诉用户。
        return  # 结束当前流程，不再继续往下走。

    promptText = readCommandPrompt(event.message_str or "")  # 去掉 /生图，留下真正提示词。
    prompt = preset.resolvePrompt(store, promptText, store.data.imageDefault.aspectRatio, store.data.imageDefault.resolution)  # 如果第一个词是预设名，就展开它。
    logger.info(f"[ImageGen] 收到生图指令 - 用户: {maskSensitive(userID)}, 输入: {promptText}")  # 日志里用户 ID 脱敏。
    if not prompt.prompt:  # 先判断这个情况，避免后面流程出错。
        yield event.plain_result("请提供图片生成的提示词或预设名称。")  # 空提示词无法生图。
        return  # 结束当前流程，不再继续往下走。

    pictures = await readReferencePictures(store, event)  # 当前模型支持图生图时，读取消息里的参考图。
    taskID = createTaskID(userID)  # 生成短任务号，用户和日志都能对上。
    yield event.plain_result(formatStartMessage(taskID, pictures, prompt.matchedName))  # 先告诉用户任务开始了。
    store.startBackground(  # 这一行按当前流程执行，作用见上方说明。
        generateAndSend(store, prompt.prompt, event.unified_msg_origin, pictures or None, prompt.aspectRatio, prompt.resolution, taskID),  # 这一行按当前流程执行，作用见上方说明。
        f"image_{taskID}",  # 这一行按当前流程执行，作用见上方说明。
    )  # 真正生图很慢，所以放到后台跑。


async def startFromTool(  # 定义一个需要等待网络或文件的异步动作。
    store: ImageStore,  # 这一行按当前流程执行，作用见上方说明。
    event: AstrMessageEvent,  # 这一行按当前流程执行，作用见上方说明。
    prompt: str,  # 这一行按当前流程执行，作用见上方说明。
    aspectRatio: str | None = None,  # 保存这一项数据，后面的流程会继续使用。
    resolution: str | None = None,  # 保存这一项数据，后面的流程会继续使用。
    avatarReferences: list[str] | None = None,  # 保存这一项数据，后面的流程会继续使用。
) -> str:  # 这一行按当前流程执行，作用见上方说明。
    """LLM 自动调用生图工具时从这里开始。"""
    if not prompt.strip():  # 先判断这个情况，避免后面流程出错。
        return "请提供图片生成的提示词。"  # LLM 没给提示词时不能生图。

    checkResult = store.data.checkUserCanGenerate(event.unified_msg_origin)  # 工具调用也要遵守用户限制。
    if isinstance(checkResult, str):  # 先判断这个情况，避免后面流程出错。
        return checkResult  # 把结果交回调用者，这就是本步的反馈。
    if not store.data.currentProvider or not store.data.currentProvider.apiKeys:  # 先判断这个情况，避免后面流程出错。
        return "未配置 API Key，无法生成图片。"  # 没 Key 时直接告诉用户配置问题。

    pictures = await readReferencePictures(store, event)  # 先读取聊天里已有的参考图。
    pictures.extend(await readAvatarReferences(store, event, avatarReferences or []))  # 再读取 LLM 明确要求的头像。
    taskID = createTaskID(event.unified_msg_origin)  # 生成任务号。
    finalAspectRatio = aspectRatio or store.data.imageDefault.aspectRatio  # 工具没传比例时用默认比例。
    finalResolution = resolution or store.data.imageDefault.resolution  # 工具没传清晰度时用默认清晰度。
    store.startBackground(  # 这一行按当前流程执行，作用见上方说明。
        generateAndSend(store, prompt.strip(), event.unified_msg_origin, pictures or None, finalAspectRatio, finalResolution, taskID),  # 这一行按当前流程执行，作用见上方说明。
        f"image_{taskID}",  # 这一行按当前流程执行，作用见上方说明。
    )  # 后台生成，避免阻塞 LLM 回复。
    return f"已启动{'图生图' if pictures else '文生图'}任务，任务ID：{taskID}"  # 把结果交回调用者，这就是本步的反馈。


async def generateAndSend(  # 定义一个需要等待网络或文件的异步动作。
    store: ImageStore,  # 这一行按当前流程执行，作用见上方说明。
    prompt: str,  # 这一行按当前流程执行，作用见上方说明。
    chatID: str,  # 这一行按当前流程执行，作用见上方说明。
    pictures: list[tuple[bytes, str]] | None,  # 这一行按当前流程执行，作用见上方说明。
    aspectRatio: str,  # 这一行按当前流程执行，作用见上方说明。
    resolution: str,  # 这一行按当前流程执行，作用见上方说明。
    taskID: str,  # 这一行按当前流程执行，作用见上方说明。
) -> None:  # 这一行按当前流程执行，作用见上方说明。
    """后台生成图片并发回聊天窗口。"""
    if not store.provider:  # 先判断这个情况，避免后面流程出错。
        return  # 初始化失败时没有生图接口，直接结束。

    request = await buildImageRequest(store, prompt, pictures, aspectRatio, resolution, taskID)  # 把聊天参数整理成供应商能读的请求。
    if store.concurrentLock is None:  # 先判断这个情况，避免后面流程出错。
        await generateNow(store, request, chatID)  # 没有并发门闩时直接生成。
        return  # 结束当前流程，不再继续往下走。
    async with store.concurrentLock:  # 进入异步上下文，用完后自动收尾。
        await generateNow(store, request, chatID)  # 有门闩时排队生成，避免同时跑太多。


def readCommandPrompt(messageText: str) -> str:  # 定义一个可重复调用的小动作。
    """取出 /生图 后面的提示词。"""
    parts = messageText.strip().split(maxsplit=1)  # 只切一次，保留提示词里的空格。
    return parts[1].strip() if len(parts) > 1 else ""  # 把结果交回调用者，这就是本步的反馈。


async def readReferencePictures(store: ImageStore, event: AstrMessageEvent) -> list[tuple[bytes, str]]:  # 定义一个需要等待网络或文件的异步动作。
    """从消息、回复和 @ 里读取参考图。"""
    if not store.provider or not (store.provider.getAbilities() & ImageAbility.imageToImage):  # 先判断这个情况，避免后面流程出错。
        return []  # 当前模型不支持图生图时，不浪费时间下载图片。
    if not event.message_obj or not event.message_obj.message:  # 先判断这个情况，避免后面流程出错。
        return []  # 消息里没有组件时，自然没有图片。

    pictures: list[tuple[bytes, str]] = []  # 每一项是 (图片字节, 图片格式)。
    replySenderID, atCountByUser = readReplyAndAtInfo(event)  # 先看哪些 @ 是 AstrBot 自动带的。
    for component in event.message_obj.message:  # 逐个处理这组内容，避免漏掉任何一项。
        try:  # 尝试执行可能失败的外部操作。
            pictures.extend(await readPicturesFromComponent(store, event, component, replySenderID, atCountByUser))  # 按组件类型提取图片。
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[ImageGen] 提取消息组件图片失败: {exc}")  # 某张图失败不影响其他图。
    return pictures  # 把结果交回调用者，这就是本步的反馈。


def readReplyAndAtInfo(event: AstrMessageEvent) -> tuple[str | None, dict[str, int]]:  # 定义一个可重复调用的小动作。
    """读取回复人和 @ 次数，用来过滤自动 @。"""
    replySenderID = None  # 回复消息的发送者 ID。
    atCountByUser: dict[str, int] = {}  # 每个用户被 @ 了几次。
    for component in event.message_obj.message:  # 逐个处理这组内容，避免漏掉任何一项。
        if isinstance(component, Comp.Reply) and getattr(component, "sender_id", None):  # 先判断这个情况，避免后面流程出错。
            replySenderID = str(component.sender_id)  # 记录回复消息作者。
        elif isinstance(component, Comp.At) and getattr(component, "qq", None) != "all":  # 继续判断另一种情况，让分支读起来顺。
            userID = str(component.qq)  # 被 @ 的 QQ 号。
            atCountByUser[userID] = atCountByUser.get(userID, 0) + 1  # 计数用于判断是不是手动又 @ 了一次。
    return replySenderID, atCountByUser  # 把结果交回调用者，这就是本步的反馈。


async def readPicturesFromComponent(  # 定义一个需要等待网络或文件的异步动作。
    store: ImageStore,  # 这一行按当前流程执行，作用见上方说明。
    event: AstrMessageEvent,  # 这一行按当前流程执行，作用见上方说明。
    component: object,  # 这一行按当前流程执行，作用见上方说明。
    replySenderID: str | None,  # 这一行按当前流程执行，作用见上方说明。
    atCountByUser: dict[str, int],  # 这一行按当前流程执行，作用见上方说明。
) -> list[tuple[bytes, str]]:  # 这一行按当前流程执行，作用见上方说明。
    """从一个消息组件里读取图片。"""
    pictures: list[tuple[bytes, str]] = []  # 本组件提取出的图片。
    if isinstance(component, Comp.Image):  # 先判断这个情况，避免后面流程出错。
        picture = await downloadPicture(store, component.url or component.file)  # 普通图片组件直接下载。
        if picture:  # 先判断这个情况，避免后面流程出错。
            pictures.append(picture)  # 这一行按当前流程执行，作用见上方说明。
    elif isinstance(component, Comp.Reply) and component.chain:  # 继续判断另一种情况，让分支读起来顺。
        for item in component.chain:  # 逐个处理这组内容，避免漏掉任何一项。
            if isinstance(item, Comp.Image):  # 先判断这个情况，避免后面流程出错。
                picture = await downloadPicture(store, item.url or item.file)  # 回复里的图片也可以作为参考图。
                if picture:  # 先判断这个情况，避免后面流程出错。
                    pictures.append(picture)  # 这一行按当前流程执行，作用见上方说明。
    elif isinstance(component, Comp.At):  # 继续判断另一种情况，让分支读起来顺。
        userID = shouldUseAtAvatar(event, component, replySenderID, atCountByUser)  # 判断这个 @ 是否要取头像。
        if userID:  # 先判断这个情况，避免后面流程出错。
            avatar = await readAvatar(store, userID)  # 下载头像。
            if avatar:  # 先判断这个情况，避免后面流程出错。
                pictures.append((avatar, "image/jpeg"))  # QQ 头像按 jpeg 传给供应商。
    return pictures  # 把结果交回调用者，这就是本步的反馈。


def shouldUseAtAvatar(event: AstrMessageEvent, component: Comp.At, replySenderID: str | None, atCountByUser: dict[str, int]) -> str | None:  # 定义一个可重复调用的小动作。
    """判断一个 @ 用户的头像要不要作为参考图。"""
    if not hasattr(component, "qq") or component.qq == "all":  # 先判断这个情况，避免后面流程出错。
        return None  # @ 全体不是某个人，不能取头像。
    userID = str(component.qq)  # 保存这一项数据，后面的流程会继续使用。
    if replySenderID and userID == replySenderID and atCountByUser.get(userID, 0) == 1:  # 先判断这个情况，避免后面流程出错。
        return None  # 回复消息时 AstrBot 可能自动 @ 原作者，默认不把它当参考图。
    selfID = str(event.get_self_id()).strip()  # 保存这一项数据，后面的流程会继续使用。
    if selfID and userID == selfID and atCountByUser.get(userID, 0) == 1:  # 先判断这个情况，避免后面流程出错。
        return None  # 单独 @ 机器人通常只是触发命令，不取机器人头像。
    return userID  # 把结果交回调用者，这就是本步的反馈。


async def readAvatarReferences(store: ImageStore, event: AstrMessageEvent, avatarReferences: list[str]) -> list[tuple[bytes, str]]:  # 定义一个需要等待网络或文件的异步动作。
    """读取 LLM 工具明确指定的头像。"""
    pictures: list[tuple[bytes, str]] = []  # 保存这一项数据，后面的流程会继续使用。
    for text in avatarReferences:  # 逐个处理这组内容，避免漏掉任何一项。
        userID = avatarTextToUserID(event, text)  # 把 self、sender 或 QQ 号转成用户 ID。
        if not userID:  # 先判断这个情况，避免后面流程出错。
            continue  # 这一行按当前流程执行，作用见上方说明。
        avatar = await readAvatar(store, userID)  # 下载头像。
        if avatar:  # 先判断这个情况，避免后面流程出错。
            pictures.append((avatar, "image/jpeg"))  # 这一行按当前流程执行，作用见上方说明。
    return pictures  # 把结果交回调用者，这就是本步的反馈。


def avatarTextToUserID(event: AstrMessageEvent, text: str) -> str | None:  # 定义一个可重复调用的小动作。
    """把头像引用文字转成用户 ID。"""
    cleanText = text.strip().lower()  # 去掉空格并统一小写，方便判断 self/sender。
    if cleanText == "self":  # 先判断这个情况，避免后面流程出错。
        return str(event.get_self_id())  # self 表示机器人自己。
    if cleanText == "sender":  # 先判断这个情况，避免后面流程出错。
        return str(event.get_sender_id() or event.unified_msg_origin)  # sender 表示当前发消息的人。
    return cleanText if cleanText.isdigit() else None  # 纯数字按 QQ 号处理。


async def downloadPicture(store: ImageStore, urlOrPath: str | None) -> tuple[bytes, str] | None:  # 定义一个需要等待网络或文件的异步动作。
    """下载网络图片或读取本地图片。"""
    if not urlOrPath:  # 先判断这个情况，避免后面流程出错。
        return None  # 没有地址就没有图片。
    try:  # 尝试执行可能失败的外部操作。
        if Path(urlOrPath).exists() and Path(urlOrPath).is_file():  # 先判断这个情况，避免后面流程出错。
            data = Path(urlOrPath).read_bytes()  # 本地文件直接读取。
        else:  # 前面情况都不符合时，走这个备用分支。
            fileName = f"ref_{hashlib.md5(urlOrPath.encode()).hexdigest()[:10]}"  # URL 太长，先转成短文件名。
            path = await download_image_by_url(urlOrPath, path=str(store.cacheDir / fileName))  # 交给 AstrBot 工具下载。
            data = Path(path).read_bytes() if path else b""  # 下载成功后读取文件。
        if not data:  # 先判断这个情况，避免后面流程出错。
            return None  # 把结果交回调用者，这就是本步的反馈。
        if len(data) > store.data.userLimit.maxImageSizeMB * 1024 * 1024:  # 先判断这个情况，避免后面流程出错。
            logger.warning(f"[ImageGen] 图片超过大小限制 ({store.data.userLimit.maxImageSizeMB}MB)")  # 这一行按当前流程执行，作用见上方说明。
            return None  # 太大的图不传给供应商，避免请求失败或费用异常。
        return data, detectMimeType(data)  # 返回图片内容和格式。
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[ImageGen] 获取图片失败 ({urlOrPath}): {exc}")  # 这一行按当前流程执行，作用见上方说明。
        return None  # 把结果交回调用者，这就是本步的反馈。


async def readAvatar(store: ImageStore, userID: str) -> bytes | None:  # 定义一个需要等待网络或文件的异步动作。
    """下载 QQ 头像。"""
    avatarURL = f"https://q4.qlogo.cn/headimg_dl?dst_uin={userID}&spec=640"  # QQ 头像接口地址。
    picture = await downloadPicture(store, avatarURL)  # 头像本质也是一张图片。
    return picture[0] if picture else None  # 把结果交回调用者，这就是本步的反馈。


async def buildImageRequest(  # 定义一个需要等待网络或文件的异步动作。
    store: ImageStore,  # 这一行按当前流程执行，作用见上方说明。
    prompt: str,  # 这一行按当前流程执行，作用见上方说明。
    pictures: list[tuple[bytes, str]] | None,  # 这一行按当前流程执行，作用见上方说明。
    aspectRatio: str,  # 这一行按当前流程执行，作用见上方说明。
    resolution: str,  # 这一行按当前流程执行，作用见上方说明。
    taskID: str,  # 这一行按当前流程执行，作用见上方说明。
) -> ImageRequest:  # 这一行按当前流程执行，作用见上方说明。
    """把聊天里的参数整理成 ImageRequest。"""
    abilities = store.provider.getAbilities()  # 当前供应商支持哪些能力。
    finalPictures = pictures if abilities & ImageAbility.imageToImage else None  # 不支持图生图时丢弃参考图。
    finalAspectRatio = aspectRatio if abilities & ImageAbility.aspectRatio else "自动"  # 不支持比例时改成自动。
    finalResolution = resolution if abilities & ImageAbility.resolution else "1K"  # 不支持分辨率时用默认 1K。
    safeAspectRatio = validateAspectRatio(finalAspectRatio)  # 过滤掉配置外的比例。
    safeAspectRatio = None if safeAspectRatio == "自动" else safeAspectRatio  # None 表示不把比例传给供应商。
    safeResolution = validateResolution(finalResolution)  # 过滤掉配置外的分辨率。
    pictureData = [PictureData(data=data, mimeType=mime) for data, mime in (finalPictures or [])]  # 包成图片数据对象。
    convertedPictures = await convertPictures(pictureData) if pictureData else []  # 不常见格式会转成 JPEG。
    return ImageRequest(prompt=prompt, images=convertedPictures, aspectRatio=safeAspectRatio, resolution=safeResolution, taskID=taskID)  # 把结果交回调用者，这就是本步的反馈。


async def generateNow(store: ImageStore, request: ImageRequest, chatID: str) -> None:  # 定义一个需要等待网络或文件的异步动作。
    """立刻调用供应商生成图片，并把结果发回聊天。"""
    startTime = time.time()  # 记录开始时间，用来算耗时。
    result = await store.provider.generate(request)  # 真正向 OpenAI/Gemini 等供应商发请求。
    duration = time.time() - startTime  # 生成用了几秒。
    if result.error:  # 先判断这个情况，避免后面流程出错。
        await sendFailure(store, chatID, request.taskID or "unknown", result.error, duration)  # 失败就发错误。
        return  # 结束当前流程，不再继续往下走。
    if not result.images:  # 先判断这个情况，避免后面流程出错。
        return  # 没报错但也没图，说明供应商返回异常空结果。
    store.data.recordUserUsage(chatID)  # 成功后才记录用量。
    await sendSuccess(store, chatID, request.taskID or "unknown", result.images, duration)  # 保存并发送图片。


async def sendFailure(store: ImageStore, chatID: str, taskID: str, error: str, duration: float) -> None:  # 定义一个需要等待网络或文件的异步动作。
    """把失败原因发回聊天窗口。"""
    logger.error(f"[ImageGen] 任务 {taskID} 生成失败，耗时: {duration:.2f}s，错误: {error}")  # 这一行按当前流程执行，作用见上方说明。
    await store.context.send_message(chatID, MessageChain().message(f"生成失败：{error}"))  # 这一行按当前流程执行，作用见上方说明。


async def sendSuccess(store: ImageStore, chatID: str, taskID: str, images: list[bytes], duration: float) -> None:  # 定义一个需要等待网络或文件的异步动作。
    """保存生成图并发回聊天窗口。"""
    logger.info(f"[ImageGen] 任务 {taskID} 生成成功，耗时: {duration:.2f}s，图片数量: {len(images)}")  # 这一行按当前流程执行，作用见上方说明。
    chain = MessageChain()  # AstrBot 的消息链，可以同时放图片和文字。
    for imageBytes in images:  # 逐个处理这组内容，避免漏掉任何一项。
        filePath = saveGeneratedPicture(store.cacheDir, taskID, imageBytes)  # 先把图片保存成本地文件。
        if filePath:  # 先判断这个情况，避免后面流程出错。
            chain.file_image(filePath)  # 再把本地文件加入消息链。
    info = formatSuccessInfo(store, chatID, len(images), duration)  # 按配置决定是否附带说明文字。
    if info:  # 先判断这个情况，避免后面流程出错。
        chain.message("\n" + info)  # 这一行按当前流程执行，作用见上方说明。
    await store.context.send_message(chatID, chain)  # 这一行按当前流程执行，作用见上方说明。


def formatStartMessage(taskID: str, pictures: list[tuple[bytes, str]], presetName: str | None) -> str:  # 定义一个可重复调用的小动作。
    """生成“任务已开始”的提示文字。"""
    parts = [f"已开始生图任务，任务ID：{taskID}"]  # 保存这一项数据，后面的流程会继续使用。
    if pictures:  # 先判断这个情况，避免后面流程出错。
        parts.append(f"参考图：{len(pictures)}张")  # 这一行按当前流程执行，作用见上方说明。
    if presetName:  # 先判断这个情况，避免后面流程出错。
        parts.append(f"预设：{presetName}")  # 这一行按当前流程执行，作用见上方说明。
    return "，".join(parts)  # 把结果交回调用者，这就是本步的反馈。


def formatSuccessInfo(store: ImageStore, chatID: str, imageCount: int, duration: float) -> str:  # 定义一个可重复调用的小动作。
    """生成成功后附加的说明文字。"""
    lines: list[str] = []  # 保存这一项数据，后面的流程会继续使用。
    if store.data.imageDefault.showGenerationInfo:  # 先判断这个情况，避免后面流程出错。
        lines.append(f"生成成功\n耗时：{duration:.2f}s\n数量：{imageCount}张")  # 这一行按当前流程执行，作用见上方说明。
    if store.data.imageDefault.showModelInfo and store.data.currentProvider:  # 先判断这个情况，避免后面流程出错。
        lines.append(f"模型：{store.data.currentProvider.name}/{store.data.currentProvider.model}")  # 这一行按当前流程执行，作用见上方说明。
    if store.data.userLimit.enableDailyLimit:  # 先判断这个情况，避免后面流程出错。
        lines.append(f"今日用量：{store.data.getUserUsageCount(chatID)}/{store.data.userLimit.dailyLimitCount}")  # 这一行按当前流程执行，作用见上方说明。
    return "\n".join(lines)  # 把结果交回调用者，这就是本步的反馈。
