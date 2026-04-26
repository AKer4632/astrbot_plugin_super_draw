"""
这个文件实现 Gemini 的 OpenAI 兼容接口。

它使用 /v1/chat/completions 发送多模态消息，响应可能是 b64_json、URL、Markdown 图片或 data URL，因此解析逻辑
会比原生 Gemini 更宽松。
"""

from __future__ import annotations

import base64
import re
import time
from typing import Any

import aiohttp

from astrbot.api import logger

from ..data import ImageRequest, ImageAbility
from .base import BaseProvider

geminiDefaultBaseURL = "https://generativelanguage.googleapis.com"  # 保存这一项数据，后面的流程会继续使用。


class GeminiOpenAI(BaseProvider):  # 定义一组放在一起的数据或行为。
    """Gemini OpenAI 兼容供应商。"""

    def getAbilities(self) -> ImageAbility:  # 定义一个可重复调用的小动作。
        """兼容接口支持文生图和图生图；比例和分辨率由模型兼容情况决定，旧实现不声明。"""
        return ImageAbility.textToImage | ImageAbility.imageToImage  # 把结果交回调用者，这就是本步的反馈。

    async def generateOnce(self, request: ImageRequest) -> tuple[list[bytes] | None, str | None]:  # 定义一个需要等待网络或文件的异步动作。
        """执行一次兼容聊天补全请求。"""
        response = await self.requestOpenAIStyle(self.getSession(), self.buildPayload(request), request.taskID)  # 保存这一项数据，后面的流程会继续使用。
        if response is None:  # 先判断这个情况，避免后面流程出错。
            return None, "API 请求失败"  # 把结果交回调用者，这就是本步的反馈。
        images = await self.readImages(response, request.taskID)  # 保存这一项数据，后面的流程会继续使用。
        if images:  # 先判断这个情况，避免后面流程出错。
            return images, None  # 把结果交回调用者，这就是本步的反馈。
        if response.get("choices"):  # 先判断这个情况，避免后面流程出错。
            content = response["choices"][0].get("message", {}).get("content")  # 保存这一项数据，后面的流程会继续使用。
            if isinstance(content, str) and content.strip():  # 先判断这个情况，避免后面流程出错。
                return None, f"未生成图片，API 返回文本: {content[:100]}"  # 把结果交回调用者，这就是本步的反馈。
        return None, "响应中未找到图片 data"  # 把结果交回调用者，这就是本步的反馈。

    def buildPayload(self, request: ImageRequest) -> dict:  # 定义一个可重复调用的小动作。
        """把统一请求转换成 OpenAI 兼容聊天请求。"""
        content: list[dict] = [{"type": "text", "text": f"Generate an image: {request.prompt}"}]  # 保存这一项数据，后面的流程会继续使用。
        for image in request.images:  # 逐个处理这组内容，避免漏掉任何一项。
            b64Data = base64.b64encode(image.data).decode("utf-8")  # 保存这一项数据，后面的流程会继续使用。
            content.append({"type": "image_url", "image_url": {"url": f"data:{image.mimeType};base64,{b64Data}"}})  # 这一行按当前流程执行，作用见上方说明。
        payload: dict[str, Any] = {"model": self.model, "messages": [{"role": "user", "content": content}], "modalities": ["image", "text"], "stream": False}  # 保存这一项数据，后面的流程会继续使用。
        generationConfig: dict[str, Any] = {}  # 保存这一项数据，后面的流程会继续使用。
        imageConfig: dict[str, Any] = {}  # 保存这一项数据，后面的流程会继续使用。
        if request.aspectRatio and not request.images:  # 先判断这个情况，避免后面流程出错。
            imageConfig["aspectRatio"] = request.aspectRatio  # 保存这一项数据，后面的流程会继续使用。
        if request.resolution:  # 先判断这个情况，避免后面流程出错。
            imageConfig["imageSize"] = request.resolution  # 保存这一项数据，后面的流程会继续使用。
        if imageConfig:  # 先判断这个情况，避免后面流程出错。
            generationConfig["imageConfig"] = imageConfig  # 保存这一项数据，后面的流程会继续使用。
        if generationConfig:  # 先判断这个情况，避免后面流程出错。
            payload["generationConfig"] = generationConfig  # 保存这一项数据，后面的流程会继续使用。
        return payload  # 把结果交回调用者，这就是本步的反馈。

    async def requestOpenAIStyle(self, session: aiohttp.ClientSession, payload: dict, taskID: str | None) -> dict | None:  # 定义一个需要等待网络或文件的异步动作。
        """发送 OpenAI 兼容请求。"""
        startTime = time.time()  # 保存这一项数据，后面的流程会继续使用。
        url = f"{self.baseURL or geminiDefaultBaseURL}/v1/chat/completions"  # 保存这一项数据，后面的流程会继续使用。
        try:  # 尝试执行可能失败的外部操作。
            async with session.post(url, json=payload, headers={"Authorization": f"Bearer {self.currentAPIKey()}", "Content-Type": "application/json"}, timeout=self.requestTimeout(), proxy=self.proxy) as response:  # 进入异步上下文，用完后自动收尾。
                duration = time.time() - startTime  # 保存这一项数据，后面的流程会继续使用。
                if response.status != 200:  # 先判断这个情况，避免后面流程出错。
                    errorText = await response.text()  # 保存这一项数据，后面的流程会继续使用。
                    logger.error(f"{self.logPrefix(taskID)} 错误 {response.status} (耗时: {duration:.2f}s): {errorText[:200]}")  # 这一行按当前流程执行，作用见上方说明。
                    return None  # 把结果交回调用者，这就是本步的反馈。
                return await response.json()  # 把结果交回调用者，这就是本步的反馈。
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.logPrefix(taskID)} 请求异常: {exc}")  # 这一行按当前流程执行，作用见上方说明。
            return None  # 把结果交回调用者，这就是本步的反馈。

    async def readImages(self, response: dict[str, Any], taskID: str | None = None) -> list[bytes] | None:  # 定义一个需要等待网络或文件的异步动作。
        """从多种兼容响应格式中提取图片。"""
        images: list[bytes] = []  # 保存这一项数据，后面的流程会继续使用。
        if isinstance(response.get("data"), list):  # 先判断这个情况，避免后面流程出错。
            for item in response["data"]:  # 逐个处理这组内容，避免漏掉任何一项。
                if isinstance(item, dict):  # 先判断这个情况，避免后面流程出错。
                    await self.appendImageFromItem(images, item, taskID)  # 这一行按当前流程执行，作用见上方说明。

        choices = response.get("choices")  # 保存这一项数据，后面的流程会继续使用。
        if choices:  # 先判断这个情况，避免后面流程出错。
            message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}  # 保存这一项数据，后面的流程会继续使用。
            content = message.get("content")  # 保存这一项数据，后面的流程会继续使用。
            if isinstance(content, str):  # 先判断这个情况，避免后面流程出错。
                await self.appendImagesFromText(images, content, taskID)  # 这一行按当前流程执行，作用见上方说明。
            elif isinstance(content, list):  # 继续判断另一种情况，让分支读起来顺。
                for part in content:  # 逐个处理这组内容，避免漏掉任何一项。
                    if isinstance(part, dict) and part.get("type") == "image_url":  # 先判断这个情况，避免后面流程出错。
                        await self.appendImageURL(images, part.get("image_url", {}).get("url"), taskID)  # 这一行按当前流程执行，作用见上方说明。
            for imageItem in message.get("images") or []:  # 逐个处理这组内容，避免漏掉任何一项。
                url = imageItem.get("url") or imageItem.get("image_url", {}).get("url") if isinstance(imageItem, dict) else imageItem  # 保存这一项数据，后面的流程会继续使用。
                await self.appendImageURL(images, url, taskID)  # 这一行按当前流程执行，作用见上方说明。
        return images or None  # 把结果交回调用者，这就是本步的反馈。

    async def appendImageFromItem(self, images: list[bytes], item: dict, taskID: str | None) -> None:  # 定义一个需要等待网络或文件的异步动作。
        """从 OpenAI data 项里追加一张图片。"""
        if item.get("b64_json"):  # 先判断这个情况，避免后面流程出错。
            images.append(base64.b64decode(item["b64_json"]))  # 这一行按当前流程执行，作用见上方说明。
        elif item.get("url"):  # 继续判断另一种情况，让分支读起来顺。
            await self.appendImageURL(images, item["url"], taskID)  # 这一行按当前流程执行，作用见上方说明。

    async def appendImagesFromText(self, images: list[bytes], content: str, taskID: str | None) -> None:  # 定义一个需要等待网络或文件的异步动作。
        """从 Markdown 图片和 data URL 文本里追加图片。"""
        for url in re.findall(r"!\[.*?\]\((.*?)\)", content):  # 逐个处理这组内容，避免漏掉任何一项。
            await self.appendImageURL(images, url, taskID)  # 这一行按当前流程执行，作用见上方说明。
        contentWithoutMarkdown = re.sub(r"!\[.*?\]\(.*?\)", "", content)  # 保存这一项数据，后面的流程会继续使用。
        pattern = re.compile(r"data\s*:\s*image/([a-zA-Z0-9.+-]+)\s*;\s*base64\s*,\s*([-A-Za-z0-9+/=_\s]+)", flags=re.IGNORECASE)  # 保存这一项数据，后面的流程会继续使用。
        for imageType, b64Text in pattern.findall(contentWithoutMarkdown):  # 逐个处理每段 data URL；imageType 只是格式名，当前只需要图片内容。
            images.append(base64.b64decode(b64Text))  # 这一行按当前流程执行，作用见上方说明。

    async def appendImageURL(self, images: list[bytes], url: str | None, taskID: str | None) -> None:  # 定义一个需要等待网络或文件的异步动作。
        """把 http URL 或 data URL 追加到图片列表。"""
        if not url:  # 先判断这个情况，避免后面流程出错。
            return  # 结束当前流程，不再继续往下走。
        if url.startswith("http"):  # 先判断这个情况，避免后面流程出错。
            data = await self.downloadImage(url, taskID)  # 保存这一项数据，后面的流程会继续使用。
            if data:  # 先判断这个情况，避免后面流程出错。
                images.append(data)  # 这一行按当前流程执行，作用见上方说明。
            return  # 结束当前流程，不再继续往下走。
        if url.startswith("data:image/") and ";base64," in url:  # 先判断这个情况，避免后面流程出错。
            images.append(base64.b64decode(url.partition(";base64,")[2]))  # 这一行按当前流程执行，作用见上方说明。

    async def downloadImage(self, url: str, taskID: str | None = None) -> bytes | None:  # 定义一个需要等待网络或文件的异步动作。
        """下载响应里给出的图片 URL。"""
        try:  # 尝试执行可能失败的外部操作。
            async with self.getSession().get(url, timeout=self.downloadTimeout()) as response:  # 进入异步上下文，用完后自动收尾。
                if response.status == 200:  # 先判断这个情况，避免后面流程出错。
                    return await response.read()  # 把结果交回调用者，这就是本步的反馈。
                logger.error(f"{self.logPrefix(taskID)} 下载图像失败: {response.status} - {url}")  # 这一行按当前流程执行，作用见上方说明。
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.logPrefix(taskID)} 下载图像出错: {exc}")  # 这一行按当前流程执行，作用见上方说明。
        return None  # 把结果交回调用者，这就是本步的反馈。
