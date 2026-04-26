"""
这个文件实现 Gemini 原生图像接口。

它支持文生图、图生图、宽高比和部分模型的分辨率参数。image.py 把统一 ImageRequest 传进来，
这里负责把请求翻译成 Gemini generateContent API 的格式。
"""

from __future__ import annotations

import base64
import time

import aiohttp

from astrbot.api import logger

from ..data import ImageRequest, ImageAbility
from .base import BaseProvider

geminiDefaultBaseURL = "https://generativelanguage.googleapis.com"  # 保存这一项数据，后面的流程会继续使用。
geminiSafetyCategories = ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT", "HARM_CATEGORY_CIVIC_INTEGRITY")  # 保存这一项数据，后面的流程会继续使用。


class Gemini(BaseProvider):  # 定义一组放在一起的数据或行为。
    """Gemini 原生供应商。"""

    def getAbilities(self) -> ImageAbility:  # 定义一个可重复调用的小动作。
        """Gemini 原生接口支持文生图、图生图、比例和分辨率。"""
        return ImageAbility.textToImage | ImageAbility.imageToImage | ImageAbility.aspectRatio | ImageAbility.resolution  # 把结果交回调用者，这就是本步的反馈。

    async def generateOnce(self, request: ImageRequest) -> tuple[list[bytes] | None, str | None]:  # 定义一个需要等待网络或文件的异步动作。
        """执行一次 Gemini generateContent 请求。"""
        response = await self.requestGemini(self.getSession(), self.buildPayload(request), request.taskID)  # 保存这一项数据，后面的流程会继续使用。
        if response is None:  # 先判断这个情况，避免后面流程出错。
            return None, "API 请求失败"  # 把结果交回调用者，这就是本步的反馈。
        images = self.readImages(response, request.taskID)  # 保存这一项数据，后面的流程会继续使用。
        return (images, None) if images else (None, "响应中未找到图片数据")  # 把结果交回调用者，这就是本步的反馈。

    def buildPayload(self, request: ImageRequest) -> dict:  # 定义一个可重复调用的小动作。
        """把统一请求转换成 Gemini 请求体。"""
        generationConfig: dict = {"responseModalities": ["IMAGE"]}  # 保存这一项数据，后面的流程会继续使用。
        imageConfig: dict = {}  # 保存这一项数据，后面的流程会继续使用。
        if request.aspectRatio and not request.images:  # 先判断这个情况，避免后面流程出错。
            imageConfig["aspectRatio"] = request.aspectRatio  # 保存这一项数据，后面的流程会继续使用。
        if request.resolution and "gemini-3" in self.model.lower():  # 先判断这个情况，避免后面流程出错。
            imageConfig["imageSize"] = request.resolution  # 保存这一项数据，后面的流程会继续使用。
        if imageConfig:  # 先判断这个情况，避免后面流程出错。
            generationConfig["imageConfig"] = imageConfig  # 保存这一项数据，后面的流程会继续使用。

        parts = [{"text": request.prompt}]  # 保存这一项数据，后面的流程会继续使用。
        for image in request.images:  # 逐个处理这组内容，避免漏掉任何一项。
            parts.append({"inline_data": {"mime_type": image.mimeType, "data": base64.b64encode(image.data).decode("utf-8")}})  # 这一行按当前流程执行，作用见上方说明。

        payload: dict = {"contents": [{"parts": parts}], "generationConfig": generationConfig}  # 保存这一项数据，后面的流程会继续使用。
        if self.safetySettings:  # 先判断这个情况，避免后面流程出错。
            payload["safetySettings"] = [{"category": category, "threshold": self.safetySettings} for category in geminiSafetyCategories]  # 保存这一项数据，后面的流程会继续使用。
        return payload  # 把结果交回调用者，这就是本步的反馈。

    async def requestGemini(self, session: aiohttp.ClientSession, payload: dict, taskID: str | None) -> dict | None:  # 定义一个需要等待网络或文件的异步动作。
        """发送 Gemini 请求并返回 JSON。"""
        startTime = time.time()  # 保存这一项数据，后面的流程会继续使用。
        url = f"{self.baseURL or geminiDefaultBaseURL}/v1beta/models/{self.model}:generateContent"  # 保存这一项数据，后面的流程会继续使用。
        logger.debug(f"{self.logPrefix(taskID)} 请求 -> {url}, key={self.maskedAPIKey()}")  # 保存这一项数据，后面的流程会继续使用。
        try:  # 尝试执行可能失败的外部操作。
            async with session.post(url, json=payload, headers={"Content-Type": "application/json", "x-goog-api-key": self.currentAPIKey()}, timeout=self.requestTimeout(), proxy=self.proxy) as response:  # 进入异步上下文，用完后自动收尾。
                duration = time.time() - startTime  # 保存这一项数据，后面的流程会继续使用。
                if response.status != 200:  # 先判断这个情况，避免后面流程出错。
                    errorText = await response.text()  # 保存这一项数据，后面的流程会继续使用。
                    logger.error(f"{self.logPrefix(taskID)} 错误 {response.status} (耗时: {duration:.2f}s): {errorText[:200]}")  # 这一行按当前流程执行，作用见上方说明。
                    return None  # 把结果交回调用者，这就是本步的反馈。
                return await response.json()  # 把结果交回调用者，这就是本步的反馈。
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.logPrefix(taskID)} 请求异常: {exc}")  # 这一行按当前流程执行，作用见上方说明。
            return None  # 把结果交回调用者，这就是本步的反馈。

    def readImages(self, response: dict, taskID: str | None) -> list[bytes] | None:  # 定义一个可重复调用的小动作。
        """从 Gemini 响应里提取 inline_data 图片。"""
        try:  # 尝试执行可能失败的外部操作。
            parts = response.get("candidates", [])[0].get("content", {}).get("parts", [])  # 保存这一项数据，后面的流程会继续使用。
            images = []  # 保存这一项数据，后面的流程会继续使用。
            for part in parts:  # 逐个处理这组内容，避免漏掉任何一项。
                inline_data = part.get("inline_data") or part.get("inlineData")  # 保存这一项数据，后面的流程会继续使用。
                if inline_data and inline_data.get("data"):  # 先判断这个情况，避免后面流程出错。
                    images.append(base64.b64decode(inline_data["data"]))  # 这一行按当前流程执行，作用见上方说明。
            return images or None  # 把结果交回调用者，这就是本步的反馈。
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.logPrefix(taskID)} 解析失败: {exc}")  # 这一行按当前流程执行，作用见上方说明。
            return None  # 把结果交回调用者，这就是本步的反馈。
