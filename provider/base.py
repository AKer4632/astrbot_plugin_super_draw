"""
这个文件定义所有供应商共同遵守的生图流程。

每个具体供应商只实现 getAbilities() 和 generateOnce()。公共动作放在这里：检查 API Key、创建 HTTP 会话、
失败时轮换 Key、按最大重试次数重试、最后返回统一 ImageResult。
"""

from __future__ import annotations

import abc
import asyncio

import aiohttp

from astrbot.api import logger

from ..data import ImageRequest, ImageResult, ImageAbility, ProviderConfig
from ..tool.http import defaultDownloadTimeout
from ..tool.text import maskSensitive


class BaseProvider(abc.ABC):  # 定义一组放在一起的数据或行为。
    """所有图像供应商的基类；它只处理跨供应商共同存在的网络和重试问题。"""

    def __init__(self, config: ProviderConfig):  # 定义一个可重复调用的小动作。
        self.config = config  # 保存这一项数据，后面的流程会继续使用。
        self.apiKeys = config.apiKeys or []  # 保存这一项数据，后面的流程会继续使用。
        self.currentKeyIndex = 0  # 保存这一项数据，后面的流程会继续使用。
        self.baseURL = (config.baseURL or "").rstrip("/")  # 保存这一项数据，后面的流程会继续使用。
        self.model = config.model  # 保存这一项数据，后面的流程会继续使用。
        self.proxy = config.proxy  # 保存这一项数据，后面的流程会继续使用。
        self.timeout = config.timeout  # 保存这一项数据，后面的流程会继续使用。
        self.downloadTimeoutSeconds = defaultDownloadTimeout  # 保存这一项数据，后面的流程会继续使用。
        self.maxRetryTimes = max(1, config.maxRetryTimes)  # 保存这一项数据，后面的流程会继续使用。
        self.safetySettings = config.safetySettings  # 保存这一项数据，后面的流程会继续使用。
        self.session: aiohttp.ClientSession | None = None  # 保存这一项数据，后面的流程会继续使用。

    @abc.abstractmethod  # 这一行按当前流程执行，作用见上方说明。
    def getAbilities(self) -> ImageAbility:  # 定义一个可重复调用的小动作。
        """返回供应商支持的能力；image.py 会按能力决定保留哪些参数。"""

    async def generate(self, request: ImageRequest) -> ImageResult:  # 定义一个需要等待网络或文件的异步动作。
        """统一生图入口；检查 Key、执行预检查、失败轮换 Key 并重试。"""
        if not self.apiKeys:  # 先判断这个情况，避免后面流程出错。
            return ImageResult(images=None, error="未配置 API Key")  # 把结果交回调用者，这就是本步的反馈。

        preResult = self.beforeGenerate(request)  # 保存这一项数据，后面的流程会继续使用。
        if preResult is not None:  # 先判断这个情况，避免后面流程出错。
            return preResult  # 把结果交回调用者，这就是本步的反馈。

        lastError = "生成失败"  # 保存这一项数据，后面的流程会继续使用。
        for attempt in range(self.maxRetryTimes):  # 逐个处理这组内容，避免漏掉任何一项。
            if attempt:  # 先判断这个情况，避免后面流程出错。
                logger.info(f"{self.logPrefix(request.taskID)} 重试 ({attempt + 1}/{self.maxRetryTimes})")  # 这一行按当前流程执行，作用见上方说明。
            images, error = await self.generateOnce(request)  # 保存这一项数据，后面的流程会继续使用。
            if images is not None:  # 先判断这个情况，避免后面流程出错。
                return ImageResult(images=images, error=None)  # 把结果交回调用者，这就是本步的反馈。
            lastError = error or "生成失败"  # 保存这一项数据，后面的流程会继续使用。
            if attempt < self.maxRetryTimes - 1:  # 先判断这个情况，避免后面流程出错。
                self.rotateAPIKey()  # 这一行按当前流程执行，作用见上方说明。
                if (attempt + 1) % max(1, len(self.apiKeys)) == 0:  # 先判断这个情况，避免后面流程出错。
                    await asyncio.sleep(min(2 ** ((attempt + 1) // len(self.apiKeys)), 10))  # 这一行按当前流程执行，作用见上方说明。
        return ImageResult(images=None, error=f"重试失败: {lastError}")  # 把结果交回调用者，这就是本步的反馈。

    def beforeGenerate(self, request: ImageRequest) -> ImageResult | None:  # 定义一个可重复调用的小动作。
        """供应商生成前的可选检查；默认不拦截。"""
        return None  # 把结果交回调用者，这就是本步的反馈。

    @abc.abstractmethod  # 这一行按当前流程执行，作用见上方说明。
    async def generateOnce(self, request: ImageRequest) -> tuple[list[bytes] | None, str | None]:  # 定义一个需要等待网络或文件的异步动作。
        """执行一次真实供应商请求；成功返回图片列表，失败返回错误文本。"""

    async def close(self) -> None:  # 定义一个需要等待网络或文件的异步动作。
        """关闭 HTTP 会话；插件卸载或切换供应商时调用。"""
        if self.session and not self.session.closed:  # 先判断这个情况，避免后面流程出错。
            await self.session.close()  # 这一行按当前流程执行，作用见上方说明。
        self.session = None  # 保存这一项数据，后面的流程会继续使用。

    def getSession(self) -> aiohttp.ClientSession:  # 定义一个可重复调用的小动作。
        """复用 aiohttp 会话；没有会话或已关闭时再创建。"""
        if self.session is None or self.session.closed:  # 先判断这个情况，避免后面流程出错。
            self.session = aiohttp.ClientSession()  # 保存这一项数据，后面的流程会继续使用。
        return self.session  # 把结果交回调用者，这就是本步的反馈。

    def currentAPIKey(self) -> str:  # 定义一个可重复调用的小动作。
        """返回当前使用的 API Key；没有 Key 时返回空字符串。"""
        if not self.apiKeys:  # 先判断这个情况，避免后面流程出错。
            return ""  # 把结果交回调用者，这就是本步的反馈。
        return self.apiKeys[self.currentKeyIndex % len(self.apiKeys)]  # 把结果交回调用者，这就是本步的反馈。

    def maskedAPIKey(self) -> str:  # 定义一个可重复调用的小动作。
        """返回脱敏 Key，只用于日志。"""
        return maskSensitive(self.currentAPIKey())  # 把结果交回调用者，这就是本步的反馈。

    def rotateAPIKey(self) -> None:  # 定义一个可重复调用的小动作。
        """轮换到下一个 API Key；只有多个 Key 时才会改变索引。"""
        if len(self.apiKeys) > 1:  # 先判断这个情况，避免后面流程出错。
            self.currentKeyIndex = (self.currentKeyIndex + 1) % len(self.apiKeys)  # 保存这一项数据，后面的流程会继续使用。
            logger.info(f"{self.logPrefix()} 轮换 API Key -> 索引 {self.currentKeyIndex}")  # 这一行按当前流程执行，作用见上方说明。

    def logPrefix(self, taskID: str | None = None) -> str:  # 定义一个可重复调用的小动作。
        """统一日志前缀；带任务 ID 时更容易追踪一次生图。"""
        prefix = f"[ImageGen] [{self.__class__.__name__}]"  # 保存这一项数据，后面的流程会继续使用。
        return f"{prefix} [{taskID}]" if taskID else prefix  # 把结果交回调用者，这就是本步的反馈。

    def requestTimeout(self) -> aiohttp.ClientTimeout:  # 定义一个可重复调用的小动作。
        """供应商请求超时。"""
        return aiohttp.ClientTimeout(total=self.timeout)  # 把结果交回调用者，这就是本步的反馈。

    def downloadTimeout(self) -> aiohttp.ClientTimeout:  # 定义一个可重复调用的小动作。
        """下载图片 URL 的超时。"""
        return aiohttp.ClientTimeout(total=self.downloadTimeoutSeconds)  # 把结果交回调用者，这就是本步的反馈。
