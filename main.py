"""
AstrBot 适配层：接收命令和 LLM 工具事件，调用通用生图库，再把结果发回聊天。

这个文件是插件里唯一知道 AstrBot API 的地方。它负责把聊天消息里的提示词、参考图、用户身份
整理成普通 Python 数据，然后调用 ImageGenerator.generate() 生成图片。generate.py 不知道 AstrBot，
data.py 只管数据，tool 文件夹只管通用工具。

调用示例：
插件加载时 AstrBot 会创建 SuperDraw(context, config)
用户发送 /生图 一只白色小猫
用户发送 /生图 手办化 加一个透明展示盒
用户发送 /预设
用户发送 /预设 添加 水彩:柔和水彩风格，高细节
LLM 调用 generate_image(prompt="画一只猫", aspectRatio="1:1", quality="high")
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.star_tools import StarTools
from astrbot.core.utils.io import download_image_by_url
from pydantic import Field
from pydantic.dataclasses import dataclass as pydantic_dataclass

from .data import PluginData
from .generate import ImageGenerator
from .tool.file import cleanCache, saveImage
from .tool.picture import detectMimeType


class SuperDraw(Star):
    """
    超级生图插件主类。
    事件从这里进入，指令调用 ImageGenerator，数据由 PluginData 管理，反馈通过 MessageChain 发送。
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        dataDir = StarTools.get_data_dir()  # AstrBot 给每个插件分配的数据目录
        self.data = PluginData(config, dataDir)  # 读取配置和运行时数据
        self.cacheDir = dataDir / "cache"  # 生成图和参考图临时缓存目录
        self.cacheDir.mkdir(parents=True, exist_ok=True)
        self.generator = ImageGenerator(
            apiKeys=self.data.apiKeys,
            baseURL=self.data.baseURL,
            model=self.data.model,
            proxy=self.data.proxy,
            timeout=self.data.timeout,
            maxRetry=self.data.maxRetry,
        )
        self.semaphore = asyncio.Semaphore(self.data.maxConcurrent)  # 控制同时生图数量
        self.backgroundTasks: set[asyncio.Task] = set()  # 记录后台任务，卸载时统一取消


    async def initialize(self):
        """插件加载时注册 LLM 工具，并启动缓存清理循环。"""
        if not self.data.apiKeys:
            logger.error("[SuperDraw] 未配置 API Key，生图功能不可用。")

        if self.data.enableLLMTool and self.data.apiKeys:
            self.context.add_llm_tools(ImageTool(plugin=self))
            logger.info("[SuperDraw] 已注册图像生成 LLM 工具。")

        self._startBackground(self._cleanCacheLoop(), "cache_cleanup")
        logger.info(f"[SuperDraw] 插件加载完成，模型：{self.data.model}")


    async def terminate(self):
        """插件卸载时取消后台任务并关闭 OpenAI 客户端。"""
        for task in list(self.backgroundTasks):
            if not task.done():
                task.cancel()
        if self.backgroundTasks:
            await asyncio.gather(*self.backgroundTasks, return_exceptions=True)
        self.backgroundTasks.clear()
        await self.generator.close()
        logger.info("[SuperDraw] 插件已卸载。")


    @filter.command("生图")
    async def cmdGenerate(self, event: AstrMessageEvent):
        """用户发送 /生图 时进入这里：检查限制、解析提示词、提取参考图、启动后台生图。"""
        userID = event.unified_msg_origin
        reason = self.data.checkUser(userID)
        if reason:
            yield event.plain_result(reason)
            return

        if not self.data.apiKeys:
            yield event.plain_result("未配置 API Key，无法生成图片。")
            return

        promptText = self._readCommandText(event.message_str or "")
        prompt, presetName = self.data.resolvePreset(promptText)
        if not prompt:
            yield event.plain_result("请提供提示词或预设名。")
            return

        images = await self._extractImages(event)
        taskID = self._createTaskID(userID)
        yield event.plain_result(self._formatStartMessage(taskID, images, presetName))
        self._startBackground(
            self._generateAndSend(userID, prompt, images, self.data.defaultSize, self.data.defaultQuality),
            f"generate_{taskID}",
        )


    @filter.command("预设")
    async def cmdPreset(self, event: AstrMessageEvent):
        """用户发送 /预设 时进入这里：展示、添加或删除预设。"""
        commandText = self._readCommandText(event.message_str or "")

        if not commandText:
            yield event.plain_result(self._formatPresetList())
            return

        if commandText.startswith("添加 "):
            yield event.plain_result(self._addPresetByText(commandText[3:]))
            return

        if commandText.startswith("删除 "):
            yield event.plain_result(self._removePresetByName(commandText[3:]))
            return

        yield event.plain_result("格式错误：/预设、/预设 添加 名称:内容、/预设 删除 名称")


    async def _generateAndSend(self, chatID: str, prompt: str, images: list[bytes], size: str, quality: str) -> None:
        """后台执行生图并发送结果；成功记录用量，失败发错误消息。"""
        async with self.semaphore:
            startTime = time.time()
            try:
                resultImages = await self.generator.generate(prompt, images, size, quality)
                duration = time.time() - startTime
                self.data.recordUsage(chatID)
                chain = self._buildImageChain(resultImages)
                info = self._formatSuccessInfo(chatID, len(resultImages), duration)
                if info:
                    chain.message("\n" + info)
                await self.context.send_message(chatID, chain)
            except Exception as exc:
                logger.error(f"[SuperDraw] 生成失败：{exc}")
                await self.context.send_message(chatID, MessageChain().message(f"生成失败：{exc}"))


    def _buildImageChain(self, resultImages: list[bytes]) -> MessageChain:
        """把图片字节保存成文件，并组装成 AstrBot 可发送的消息链。"""
        chain = MessageChain()
        for imageBytes in resultImages:
            filePath = saveImage(self.cacheDir, imageBytes)
            if filePath:
                chain.file_image(filePath)
        return chain


    async def _extractImages(self, event: AstrMessageEvent) -> list[bytes]:
        """从消息中提取所有参考图：图片组件、回复链、@头像、合并转发。"""
        if not event.message_obj or not event.message_obj.message:
            return []

        pictures: list[bytes] = []
        for component in event.message_obj.message:
            try:
                pictures.extend(await self._extractImagesFromComponent(component))
            except Exception as exc:
                logger.error(f"[SuperDraw] 提取参考图失败：{exc}")
        return pictures


    async def _extractImagesFromComponent(self, component: Any) -> list[bytes]:
        """从单个 AstrBot 消息组件里提取图片字节。"""
        if isinstance(component, Comp.Image):
            image = await self._downloadImage(component.url or component.file)
            return [image] if image else []

        if isinstance(component, Comp.Reply) and component.chain:
            return await self._extractImagesFromChain(component.chain)

        if isinstance(component, Comp.At) and hasattr(component, "qq") and component.qq != "all":
            image = await self._downloadAvatar(str(component.qq))
            return [image] if image else []

        if hasattr(component, "type") and getattr(component, "type", "") == "forward":
            return await self._extractImagesFromForward(component)

        return []


    async def _extractImagesFromChain(self, chain: list[Any]) -> list[bytes]:
        """从回复链或普通消息链里提取图片组件。"""
        pictures: list[bytes] = []
        for item in chain:
            if isinstance(item, Comp.Image):
                image = await self._downloadImage(item.url or item.file)
                if image:
                    pictures.append(image)
        return pictures


    async def _extractImagesFromForward(self, component: Any) -> list[bytes]:
        """从合并转发消息中提取图片，兼容 content 和 nodes 两种字段。"""
        pictures: list[bytes] = []
        nodes = getattr(component, "content", None) or getattr(component, "nodes", None) or []
        for node in nodes:
            chain = getattr(node, "chain", None) or getattr(node, "message", None) or []
            pictures.extend(await self._extractImagesFromChain(chain))
        return pictures


    async def _downloadImage(self, urlOrPath: str | None) -> bytes | None:
        """下载网络图片或读取本地文件，超过配置大小限制返回 None。"""
        if not urlOrPath:
            return None

        try:
            path = Path(urlOrPath)
            if path.exists() and path.is_file():
                data = path.read_bytes()
            else:
                fileName = f"ref_{hashlib.md5(urlOrPath.encode()).hexdigest()[:10]}"
                downloaded = await download_image_by_url(urlOrPath, path=str(self.cacheDir / fileName))
                data = Path(downloaded).read_bytes() if downloaded else b""

            if not data:
                return None
            if len(data) > self.data.maxImageSizeMB * 1024 * 1024:
                logger.info(f"[SuperDraw] 参考图超过 {self.data.maxImageSizeMB}MB，已忽略。")
                return None

            # 这里调用 detectMimeType 是为了确认它确实像图片；未知格式也交给模型尝试
            detectMimeType(data)
            return data
        except Exception as exc:
            logger.error(f"[SuperDraw] 获取图片失败 ({urlOrPath})：{exc}")
            return None


    async def _downloadAvatar(self, userID: str) -> bytes | None:
        """下载 QQ 头像作为参考图。"""
        url = f"https://q4.qlogo.cn/headimg_dl?dst_uin={userID}&spec=640"
        return await self._downloadImage(url)


    async def _cleanCacheLoop(self) -> None:
        """定时清理缓存目录，插件启动时先清一次，之后按配置间隔清理。"""
        while True:
            try:
                deletedCount = await cleanCache(self.cacheDir, self.data.maxCacheCount)
                if deletedCount:
                    logger.info(f"[SuperDraw] 已清理 {deletedCount} 个旧缓存文件。")
                await asyncio.sleep(self.data.cleanupIntervalHours * 3600)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[SuperDraw] 清理缓存失败：{exc}")
                await asyncio.sleep(60)


    def _startBackground(self, coro, name: str) -> asyncio.Task:
        """启动后台任务并记录下来，插件卸载时可以统一取消。"""
        task = asyncio.create_task(coro)
        task.set_name(name)
        self.backgroundTasks.add(task)
        task.add_done_callback(self.backgroundTasks.discard)
        return task


    def _readCommandText(self, messageText: str) -> str:
        """取出命令后面的正文，例如 '/生图 一只猫' 得到 '一只猫'。"""
        parts = messageText.strip().split(maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else ""


    def _createTaskID(self, seed: str) -> str:
        """用当前时间和用户 ID 生成 8 位任务 ID，方便用户识别任务。"""
        return hashlib.md5(f"{time.time()}{seed}".encode()).hexdigest()[:8]


    def _formatStartMessage(self, taskID: str, images: list[bytes], presetName: str | None) -> str:
        """生成任务开始提示文字。"""
        parts = [f"已开始生图任务，任务ID：{taskID}"]
        if images:
            parts.append(f"参考图：{len(images)}张")
        if presetName:
            parts.append(f"预设：{presetName}")
        return "，".join(parts)


    def _formatSuccessInfo(self, chatID: str, imageCount: int, duration: float) -> str:
        """生成成功后附加的说明文字，受配置开关控制。"""
        lines: list[str] = []
        if self.data.showInfo:
            lines.append(f"生成成功\n耗时：{duration:.2f}s\n数量：{imageCount}张")
        if self.data.showModel:
            lines.append(f"模型：{self.data.model}")
        if self.data.enableDailyLimit:
            lines.append(f"今日用量：{self.data.getUserUsageCount(chatID)}/{self.data.dailyLimitCount}")
        return "\n".join(lines)


    def _formatPresetList(self) -> str:
        """把预设字典格式化成聊天消息。"""
        if not self.data.presets:
            return "当前没有预设。"
        lines = ["预设列表："]
        for index, (name, prompt) in enumerate(self.data.presets.items(), 1):
            shortPrompt = prompt[:20] + "..." if len(prompt) > 20 else prompt
            lines.append(f"{index}. {name}: {shortPrompt}")
        return "\n".join(lines)


    def _addPresetByText(self, text: str) -> str:
        """解析 '名称:内容' 并保存预设。"""
        if ":" not in text:
            return "格式错误：/预设 添加 名称:内容"

        name, prompt = text.split(":", 1)
        if not name.strip() or not prompt.strip():
            return "格式错误：名称和内容都不能为空。"

        self.data.addPreset(name.strip(), prompt.strip())
        return f"预设已添加：{name.strip()}"


    def _removePresetByName(self, name: str) -> str:
        """按名称删除预设。"""
        presetName = name.strip()
        if not presetName:
            return "请提供要删除的预设名称。"
        if self.data.removePreset(presetName):
            return f"预设已删除：{presetName}"
        return f"预设不存在：{presetName}"


@pydantic_dataclass
class ImageTool(FunctionTool[AstrAgentContext]):
    """
    给 LLM 调用的图像生成工具。
    它是另一种触发入口：LLM 给参数，这里调用插件的后台生图流程。
    """

    name: str = "generate_image"
    description: str = "生成或修改图片"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "生图提示词，保留用户真实意图。"},
                "aspectRatio": {"type": "string", "enum": ["auto", "1:1", "2:3", "3:2", "9:16", "16:9"], "default": "auto"},
                "quality": {"type": "string", "enum": ["low", "medium", "high", "auto"], "default": "auto"},
            },
            "required": ["prompt"],
        }
    )
    plugin: Any = None


    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs: Any) -> ToolExecResult:
        """LLM 调用工具时进入这里，启动后台生图并立即返回文字反馈。"""
        event = self._readEvent(context)
        if not event:
            return "无法获取当前消息上下文。"
        if not self.plugin:
            return "插件还没有正确初始化。"

        prompt = str(kwargs.get("prompt", "")).strip()
        if not prompt:
            return "请提供图片生成提示词。"

        reason = self.plugin.data.checkUser(event.unified_msg_origin)
        if reason:
            return reason

        size = PluginData.mapAspectRatio(str(kwargs.get("aspectRatio", "auto")))
        quality = str(kwargs.get("quality", "auto"))
        images = await self.plugin._extractImages(event)
        self.plugin._startBackground(
            self.plugin._generateAndSend(event.unified_msg_origin, prompt, images, size, quality),
            f"llm_generate_{self.plugin._createTaskID(event.unified_msg_origin)}",
        )
        return f"已启动{'图生图' if images else '文生图'}任务。"


    def _readEvent(self, context: ContextWrapper[AstrAgentContext]) -> Any:
        """从 LLM 工具上下文里取当前消息事件。"""
        if hasattr(context, "context") and isinstance(context.context, AstrAgentContext):
            return context.context.event
        if isinstance(context, dict):
            return context.get("event")
        return None
