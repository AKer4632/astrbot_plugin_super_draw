"""
这个文件实现 Z-Image Gitee AI 接口。

Z-Image 当前只支持文生图，所以如果请求里带参考图，会在生成前直接返回明确错误。
"""

from __future__ import annotations

import base64
import time
from typing import Any

from astrbot.api import logger

from ..data import ImageRequest, ImageResult, ImageAbility
from .base import BaseProvider

giteeAIDefaultBaseURL = "https://ai.gitee.com"  # 保存这一项数据，后面的流程会继续使用。
resolution1KMap = {"1:1": "1024x1024", "4:3": "1024x768", "3:4": "768x1024", "16:9": "1024x576", "9:16": "576x1024", "3:2": "1024x640", "2:3": "640x1024"}  # 保存这一项数据，后面的流程会继续使用。
resolution2KMap = {"1:1": "2048x2048", "4:3": "2048x1536", "3:4": "1536x2048", "3:2": "2048x1360", "2:3": "1360x2048", "16:9": "2048x1152", "9:16": "1152x2048"}  # 保存这一项数据，后面的流程会继续使用。


class ZImage(BaseProvider):  # 定义一组放在一起的数据或行为。
    """Z-Image 图像供应商。"""

    def getAbilities(self) -> ImageAbility:  # 定义一个可重复调用的小动作。
        """Z-Image 支持文生图、比例和分辨率，不支持参考图。"""
        return ImageAbility.textToImage | ImageAbility.resolution | ImageAbility.aspectRatio  # 把结果交回调用者，这就是本步的反馈。

    def beforeGenerate(self, request: ImageRequest) -> ImageResult | None:  # 定义一个可重复调用的小动作。
        """Z-Image 不支持图生图，提前返回错误能节省一次 API 请求。"""
        if request.images:  # 先判断这个情况，避免后面流程出错。
            return ImageResult(images=None, error="Z-Image 目前仅支持文生图，请勿上传图片。")  # 把结果交回调用者，这就是本步的反馈。
        logger.info(f"{self.logPrefix(request.taskID)} 开始生成: prompt='{request.prompt[:50]}...', model='{self.model or 'z-image-turbo'}'")  # 保存这一项数据，后面的流程会继续使用。
        return None  # 把结果交回调用者，这就是本步的反馈。

    async def generateOnce(self, request: ImageRequest) -> tuple[list[bytes] | None, str | None]:  # 定义一个需要等待网络或文件的异步动作。
        """执行一次 Z-Image 请求。"""
        startTime = time.time()  # 保存这一项数据，后面的流程会继续使用。
        url = f"{(self.baseURL or giteeAIDefaultBaseURL).rstrip('/')}/v1/images/generations"  # 保存这一项数据，后面的流程会继续使用。
        headers = {"Authorization": f"Bearer {self.currentAPIKey()}", "Content-Type": "application/json", "X-Failover-Enabled": "true"}  # 保存这一项数据，后面的流程会继续使用。
        try:  # 尝试执行可能失败的外部操作。
            async with self.getSession().post(url, json=self.buildPayload(request), headers=headers, proxy=self.proxy, timeout=self.requestTimeout()) as response:  # 进入异步上下文，用完后自动收尾。
                duration = time.time() - startTime  # 保存这一项数据，后面的流程会继续使用。
                if response.status != 200:  # 先判断这个情况，避免后面流程出错。
                    logger.error(f"{self.logPrefix(request.taskID)} API 错误 ({response.status}, 耗时: {duration:.2f}s): {await response.text()}")  # 这一行按当前流程执行，作用见上方说明。
                    return None, f"API 错误 ({response.status})"  # 把结果交回调用者，这就是本步的反馈。
                logger.info(f"{self.logPrefix(request.taskID)} 生成成功 (耗时: {duration:.2f}s)")  # 这一行按当前流程执行，作用见上方说明。
                return await self.readImages(await response.json(), request.taskID)  # 把结果交回调用者，这就是本步的反馈。
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.logPrefix(request.taskID)} 请求异常: {exc}")  # 这一行按当前流程执行，作用见上方说明。
            return None, str(exc)  # 把结果交回调用者，这就是本步的反馈。

    def buildPayload(self, request: ImageRequest) -> dict:  # 定义一个可重复调用的小动作。
        """把比例和分辨率映射成 Gitee AI 的 size。"""
        aspectRatio = request.aspectRatio or "1:1"  # 保存这一项数据，后面的流程会继续使用。
        if aspectRatio == "自动":  # 先判断这个情况，避免后面流程出错。
            aspectRatio = "1:1"  # 保存这一项数据，后面的流程会继续使用。
        size = resolution2KMap.get(aspectRatio, "2048x2048") if request.resolution in ("2K", "4K") else resolution1KMap.get(aspectRatio, "1024x1024")  # 保存这一项数据，后面的流程会继续使用。
        payload: dict[str, Any] = {"model": self.model or "z-image-turbo", "prompt": request.prompt, "size": size, "num_inference_steps": 9}  # 保存这一项数据，后面的流程会继续使用。
        return payload  # 把结果交回调用者，这就是本步的反馈。

    async def readImages(self, data: dict, taskID: str | None = None) -> tuple[list[bytes] | None, str | None]:  # 定义一个需要等待网络或文件的异步动作。
        """从 Gitee AI 响应里读取 b64_json 或 URL 图片。"""
        if "data" not in data:  # 先判断这个情况，避免后面流程出错。
            return None, f"响应格式错误: {data}"  # 把结果交回调用者，这就是本步的反馈。
        images = []  # 保存这一项数据，后面的流程会继续使用。
        for item in data["data"]:  # 逐个处理这组内容，避免漏掉任何一项。
            if "b64_json" in item:  # 先判断这个情况，避免后面流程出错。
                images.append(base64.b64decode(item["b64_json"]))  # 这一行按当前流程执行，作用见上方说明。
            elif "url" in item:  # 继续判断另一种情况，让分支读起来顺。
                image = await self.downloadImage(item["url"], taskID)  # 保存这一项数据，后面的流程会继续使用。
                if image:  # 先判断这个情况，避免后面流程出错。
                    images.append(image)  # 这一行按当前流程执行，作用见上方说明。
        return (images, None) if images else (None, "未生成任何图像")  # 把结果交回调用者，这就是本步的反馈。

    async def downloadImage(self, url: str, taskID: str | None = None) -> bytes | None:  # 定义一个需要等待网络或文件的异步动作。
        """下载 Gitee AI 返回的图片 URL。"""
        try:  # 尝试执行可能失败的外部操作。
            async with self.getSession().get(url, proxy=self.proxy, timeout=self.downloadTimeout()) as resp:  # 进入异步上下文，用完后自动收尾。
                if resp.status == 200:  # 先判断这个情况，避免后面流程出错。
                    return await resp.read()  # 把结果交回调用者，这就是本步的反馈。
                logger.error(f"{self.logPrefix(taskID)} 下载图像失败 ({resp.status}): {url}")  # 这一行按当前流程执行，作用见上方说明。
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.logPrefix(taskID)} 下载图像异常: {exc}")  # 这一行按当前流程执行，作用见上方说明。
        return None  # 把结果交回调用者，这就是本步的反馈。
