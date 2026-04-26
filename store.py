"""
这个文件只保存插件运行时会共享的东西。

把它想成一个“桌面”：AstrBot 上下文、配置数据、当前生图接口、缓存目录、后台任务，都放在这张桌面上。
其他文件需要什么就从 store 里拿，不再到处传一大堆零散参数。

真实调用例子：
store = ImageStore(context=context, rawConfig=config, dataDir=dataDir, cacheDir=dataDir / "cache")
store.createProvider()
store.startBackground(coro, "image_abc123")
await store.stopAllTasks()
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from astrbot.api.star import Context
from astrbot.core.config.astrbot_config import AstrBotConfig

from .data import ImageData
from .provider import BaseProvider, createProvider


@dataclass  # 这一行按当前流程执行，作用见上方说明。
class ImageStore:  # 定义一组放在一起的数据或行为。
    """插件共享状态；这里不写生图逻辑，只保存大家都会用到的对象。"""

    context: Context  # AstrBot 上下文；发消息和注册工具都要用它。
    rawConfig: AstrBotConfig  # AstrBot 原始配置；data.py 会读取和保存它。
    dataDir: Path  # 插件数据目录；usage.json 会放这里。
    cacheDir: Path  # 图片缓存目录；生成图会先保存到这里再发送。
    data: ImageData = field(init=False)  # 插件整理后的配置和用量数据。
    provider: BaseProvider | None = None  # 当前生图接口，例如 OpenAI 或 Gemini。
    concurrentLock: asyncio.Semaphore | None = None  # 同时生图数量的门闩，防止一下子跑太多任务。
    backgroundTasks: set[asyncio.Task] = field(default_factory=set)  # 正在后台运行的任务。
    loopTasks: dict[str, asyncio.Task] = field(default_factory=dict)  # 固定间隔任务，例如清理缓存。
    dailyTaskDates: dict[str, str] = field(default_factory=dict)  # 每日任务上次执行日期。

    def __post_init__(self) -> None:  # 定义一个可重复调用的小动作。
        """对象创建后立刻准备缓存目录和数据入口。"""
        self.cacheDir.mkdir(parents=True, exist_ok=True)  # 目录不存在就创建，保存图片时就不会失败。
        self.data = ImageData(self.rawConfig, self.dataDir)  # 把 AstrBot 配置整理成人好读的数据。

    def createProvider(self) -> bool:  # 定义一个可重复调用的小动作。
        """按当前模型创建生图接口；成功返回 True，没配置模型返回 False。"""
        if not self.data.currentProvider:  # 先判断这个情况，避免后面流程出错。
            return False  # 没有供应商配置时不能生图。

        self.provider = createProvider(self.data.currentProvider)  # 根据供应商类型创建 OpenAI/Gemini 等对象。
        self.concurrentLock = asyncio.Semaphore(self.data.imageDefault.maxConcurrentTasks)  # 限制同时生图数量。
        return True  # 把结果交回调用者，这就是本步的反馈。

    async def changeProvider(self) -> bool:  # 定义一个需要等待网络或文件的异步动作。
        """切换模型后重建生图接口。"""
        await self.closeProvider()  # 先关旧接口，释放 HTTP 会话。
        return self.createProvider()  # 再按新配置创建接口。

    def startBackground(self, coro: Coroutine[Any, Any, Any], name: str | None = None) -> asyncio.Task:  # 定义一个可重复调用的小动作。
        """启动后台任务并记录下来，插件卸载时可以统一取消。"""
        task = asyncio.create_task(coro)  # 把协程交给事件循环运行。
        if name:  # 先判断这个情况，避免后面流程出错。
            task.set_name(name)  # 任务名只用于调试和日志，不影响业务。
        self.backgroundTasks.add(task)  # 记住任务，后面卸载插件时要取消它。
        task.add_done_callback(self.backgroundTasks.discard)  # 任务结束后自动从集合里移除。
        return task  # 把结果交回调用者，这就是本步的反馈。

    async def closeProvider(self) -> None:  # 定义一个需要等待网络或文件的异步动作。
        """关闭当前生图接口。"""
        if self.provider:  # 先判断这个情况，避免后面流程出错。
            await self.provider.close()  # 关闭 aiohttp 会话，避免资源泄漏。
        self.provider = None  # 保存这一项数据，后面的流程会继续使用。

    async def stopAllTasks(self) -> None:  # 定义一个需要等待网络或文件的异步动作。
        """取消所有后台任务。"""
        for task in list(self.backgroundTasks):  # 逐个处理这组内容，避免漏掉任何一项。
            if not task.done():  # 先判断这个情况，避免后面流程出错。
                task.cancel()  # 还没结束的任务发取消信号。
        if self.backgroundTasks:  # 先判断这个情况，避免后面流程出错。
            await asyncio.gather(*self.backgroundTasks, return_exceptions=True)  # 等任务收尾，异常不再向外抛。
        self.backgroundTasks.clear()  # 清空任务记录。
        self.loopTasks.clear()  # 清空循环任务记录。
        self.dailyTaskDates.clear()  # 清空每日任务日期记录。
