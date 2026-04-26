"""
这个文件实现 Grok xAI 图像接口。

Grok 支持文生图和带参考图的 edits 接口，宽高比和分辨率需要转换成它接受的小写格式。
"""

from __future__ import annotations

import base64
import time
from typing import Any

from astrbot.api import logger

from ..data import ImageRequest, ImageAbility
from .base import BaseProvider


class Grok(BaseProvider):  # 定义一组放在一起的数据或行为。
    """Grok 图像供应商。"""

    def getAbilities(self) -> ImageAbility:  # 定义一个可重复调用的小动作。
        """Grok 支持文生图、图生图、比例和分辨率。"""
        return ImageAbility.textToImage | ImageAbility.aspectRatio | ImageAbility.resolution | ImageAbility.imageToImage  # 把结果交回调用者，这就是本步的反馈。

    async def generateOnce(self, request: ImageRequest) -> tuple[list[bytes] | None, str | None]:  # 定义一个需要等待网络或文件的异步动作。
        """执行一次 Grok 图片请求。"""
        startTime = time.time()  # 保存这一项数据，后面的流程会继续使用。
        endPoint = "/images/edits" if request.images else "/images/generations"  # 保存这一项数据，后面的流程会继续使用。
        url = f"{self.baseURL.rstrip('/')}/v1{endPoint}" if self.baseURL else f"https://api.x.ai/v1{endPoint}"  # 保存这一项数据，后面的流程会继续使用。
        headers = {"Authorization": f"Bearer {self.currentAPIKey()}", "Content-Type": "application/json"}  # 保存这一项数据，后面的流程会继续使用。
        try:  # 尝试执行可能失败的外部操作。
            async with self.getSession().post(url, json=self.buildPayload(request), headers=headers, proxy=self.proxy, timeout=self.requestTimeout()) as response:  # 进入异步上下文，用完后自动收尾。
                duration = time.time() - startTime  # 保存这一项数据，后面的流程会继续使用。
                if response.status != 200:  # 先判断这个情况，避免后面流程出错。
                    logger.error(f"{self.logPrefix(request.taskID)} API 错误 ({response.status}, 耗时: {duration:.2f}s): {await response.text()}")  # 这一行按当前流程执行，作用见上方说明。
                    return None, f"API 错误 ({response.status})"  # 把结果交回调用者，这就是本步的反馈。
                logger.info(f"{self.logPrefix(request.taskID)} 生成成功 (耗时: {duration:.2f}s)")  # 这一行按当前流程执行，作用见上方说明。
                return await self.readImages(await response.json())  # 把结果交回调用者，这就是本步的反馈。
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.logPrefix(request.taskID)} 请求异常: {exc}")  # 这一行按当前流程执行，作用见上方说明。
            return None, str(exc)  # 把结果交回调用者，这就是本步的反馈。

    def buildPayload(self, request: ImageRequest) -> dict:  # 定义一个可重复调用的小动作。
        """把统一请求转换成 Grok 请求体。"""
        acceptRatio = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "1:2", "2:1", "19.5:9", "9:19.5", "20:9", "9:20"]  # 保存这一项数据，后面的流程会继续使用。
        ratio = request.aspectRatio if request.aspectRatio in acceptRatio else "auto"  # 保存这一项数据，后面的流程会继续使用。
        resolution = request.resolution.lower() if request.resolution and request.resolution.lower() in ["1k", "2k"] else "2k"  # 保存这一项数据，后面的流程会继续使用。
        imagesRef = [{"type": "image_url", "url": f"data:{image.mimeType};base64,{base64.b64encode(image.data).decode('utf-8')}"} for image in request.images]  # 保存这一项数据，后面的流程会继续使用。
        payload: dict[str, Any] = {"model": self.model or "grok-imagine-image", "prompt": request.prompt, "aspect_ratio": ratio, "resolution": resolution, "response_format": "b64_json"}  # 保存这一项数据，后面的流程会继续使用。
        if imagesRef:  # 先判断这个情况，避免后面流程出错。
            payload["images"] = imagesRef  # 保存这一项数据，后面的流程会继续使用。
        return payload  # 把结果交回调用者，这就是本步的反馈。

    async def readImages(self, response: dict) -> tuple[list[bytes] | None, str | None]:  # 定义一个需要等待网络或文件的异步动作。
        """从 Grok 响应 data 数组读取图片。"""
        if "data" not in response:  # 先判断这个情况，避免后面流程出错。
            return None, "响应中未找到 data 字段"  # 把结果交回调用者，这就是本步的反馈。
        images = []  # 保存这一项数据，后面的流程会继续使用。
        for item in response["data"]:  # 逐个处理这组内容，避免漏掉任何一项。
            if "b64_json" in item:  # 先判断这个情况，避免后面流程出错。
                images.append(base64.b64decode(item["b64_json"]))  # 这一行按当前流程执行，作用见上方说明。
            elif "url" in item:  # 继续判断另一种情况，让分支读起来顺。
                async with self.getSession().get(item["url"], proxy=self.proxy, timeout=self.downloadTimeout()) as resp:  # 进入异步上下文，用完后自动收尾。
                    if resp.status == 200:  # 先判断这个情况，避免后面流程出错。
                        images.append(await resp.read())  # 这一行按当前流程执行，作用见上方说明。
        return (images, None) if images else (None, "未找到有效的图片数据")  # 把结果交回调用者，这就是本步的反馈。
