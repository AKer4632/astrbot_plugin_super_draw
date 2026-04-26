"""
这是 AstrBot 图像生成插件的唯一入口。

入口文件只保留 AstrBot 必须识别的格式：ImageGenerationPlugin、initialize()、terminate() 和三个命令装饰器。
真正业务都在根目录主体文件里：image.py 负责生图，model.py 负责模型，preset.py 负责预设，task.py 负责后台任务，
data.py 负责配置和用量数据，provider/ 负责供应商请求。
"""

from __future__ import annotations

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.star_tools import StarTools

from . import astrbotTool, image, model, preset, task
from .store import ImageStore


class ImageGenerationPlugin(Star):  # 定义一组放在一起的数据或行为。
    """AstrBot 插件主类；格式保持不变，内部只分发触发事件。"""

    def __init__(self, context: Context, config: AstrBotConfig):  # 定义一个可重复调用的小动作。
        super().__init__(context)  # 这一行按当前流程执行，作用见上方说明。
        dataDir = StarTools.get_data_dir()  # AstrBot 给插件的数据目录。
        self.store = ImageStore(context=context, rawConfig=config, dataDir=dataDir, cacheDir=dataDir / "cache")  # 创建共享状态。

    async def initialize(self):  # 定义一个需要等待网络或文件的异步动作。
        """AstrBot 加载插件时调用；创建供应商、注册 LLM 工具、启动后台任务。"""
        if not self.store.createProvider():  # 先判断这个情况，避免后面流程出错。
            logger.error("[ImageGen] 没有找到有效的生图模型配置，插件只会保留命令入口。")  # 这一行按当前流程执行，作用见上方说明。
        if self.store.data.enableLLMTool and self.store.provider:  # 先判断这个情况，避免后面流程出错。
            self.store.context.add_llm_tools(astrbotTool.createImageTool(self.store))  # 这一行按当前流程执行，作用见上方说明。
            logger.info("[ImageGen] 已注册图像生成 LLM 工具。")  # 这一行按当前流程执行，作用见上方说明。
        task.start(self.store)  # 这一行按当前流程执行，作用见上方说明。
        currentModel = self.store.data.currentProvider.model if self.store.data.currentProvider else "未知"  # 日志里展示当前模型。
        logger.info(f"[ImageGen] 插件加载完成，当前模型：{currentModel}")  # 这一行按当前流程执行，作用见上方说明。

    async def terminate(self):  # 定义一个需要等待网络或文件的异步动作。
        """AstrBot 卸载插件时调用；取消后台任务并关闭供应商 HTTP 会话。"""
        try:  # 尝试执行可能失败的外部操作。
            await self.store.stopAllTasks()  # 这一行按当前流程执行，作用见上方说明。
            await self.store.closeProvider()  # 这一行按当前流程执行，作用见上方说明。
            logger.info("[ImageGen] 插件已卸载。")  # 这一行按当前流程执行，作用见上方说明。
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[ImageGen] 卸载清理出错：{exc}")  # 这一行按当前流程执行，作用见上方说明。

    @filter.command("生图")  # 这一行按当前流程执行，作用见上方说明。
    async def generateImageCommand(self, event: AstrMessageEvent):  # 定义一个需要等待网络或文件的异步动作。
        """用户命令 /生图；入口只转交给 image.py。"""
        async for result in image.startFromCommand(self.store, event):  # 这一行按当前流程执行，作用见上方说明。
            yield result  # 这一行按当前流程执行，作用见上方说明。

    @filter.command("生图模型")  # 这一行按当前流程执行，作用见上方说明。
    async def modelCommand(self, event: AstrMessageEvent, modelIndex: str = ""):  # 定义一个需要等待网络或文件的异步动作。
        """用户命令 /生图模型；入口只转交给 model.py。"""
        async for result in model.showOrSwitch(self.store, event, modelIndex):  # 这一行按当前流程执行，作用见上方说明。
            yield result  # 这一行按当前流程执行，作用见上方说明。

    @filter.command("预设")  # 这一行按当前流程执行，作用见上方说明。
    async def presetCommand(self, event: AstrMessageEvent):  # 定义一个需要等待网络或文件的异步动作。
        """用户命令 /预设；入口只转交给 preset.py。"""
        async for result in preset.showOrChange(self.store, event):  # 这一行按当前流程执行，作用见上方说明。
            yield result  # 这一行按当前流程执行，作用见上方说明。
