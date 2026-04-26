"""
这个文件实现 Jimeng2API 图像生成和自动领积分。

Jimeng 的文生图走 /v1/images/generations，图生图走 /v1/images/compositions。每日领积分是后台任务调用
receiveToken()，它和生图使用同一份 API Key 配置。
"""

from __future__ import annotations

import base64
import time
from typing import Any

from astrbot.api import logger

from ..data import ImageRequest, ImageAbility
from .base import BaseProvider


class Jimeng(BaseProvider):  # 定义一组放在一起的数据或行为。
    """Jimeng2API 图像供应商。"""

    def getAbilities(self) -> ImageAbility:  # 定义一个可重复调用的小动作。
        """Jimeng2API 支持文生图、图生图、比例和分辨率。"""
        return ImageAbility.textToImage | ImageAbility.imageToImage | ImageAbility.resolution | ImageAbility.aspectRatio  # 把结果交回调用者，这就是本步的反馈。

    async def generateOnce(self, request: ImageRequest) -> tuple[list[bytes] | None, str | None]:  # 定义一个需要等待网络或文件的异步动作。
        """按是否有参考图选择文生图或图生图接口。"""
        startTime = time.time()  # 保存这一项数据，后面的流程会继续使用。
        base_url = self.baseURL or "http://localhost:5100"  # 保存这一项数据，后面的流程会继续使用。
        endpoint = "/v1/images/compositions" if request.images else "/v1/images/generations"  # 保存这一项数据，后面的流程会继续使用。
        url = f"{base_url.rstrip('/')}{endpoint}"  # 保存这一项数据，后面的流程会继续使用。
        headers = {"Authorization": f"Bearer {self.currentAPIKey()}", "Content-Type": "application/json"}  # 保存这一项数据，后面的流程会继续使用。
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

    def buildPayload(self, request: ImageRequest) -> dict[str, object]:  # 定义一个可重复调用的小动作。
        """把统一请求转换成 Jimeng2API 请求体。"""
        payload: dict[str, object] = {"model": self.model or "jimeng-4.5", "prompt": str(request.prompt)}  # 保存这一项数据，后面的流程会继续使用。
        if request.images:  # 先判断这个情况，避免后面流程出错。
            payload["images"] = [f"data:{image.mimeType or 'image/jpeg'};base64,{base64.b64encode(image.data).decode('ascii')}" for image in request.images]  # 保存这一项数据，后面的流程会继续使用。
        else:  # 前面情况都不符合时，走这个备用分支。
            payload["response_format"] = "url"  # 保存这一项数据，后面的流程会继续使用。
        if request.aspectRatio:  # 先判断这个情况，避免后面流程出错。
            if request.aspectRatio == "自动":  # 先判断这个情况，避免后面流程出错。
                payload["intelligent_ratio"] = True  # 保存这一项数据，后面的流程会继续使用。
            else:  # 前面情况都不符合时，走这个备用分支。
                payload["ratio"] = request.aspectRatio  # 保存这一项数据，后面的流程会继续使用。
        if request.resolution:  # 先判断这个情况，避免后面流程出错。
            payload["resolution"] = request.resolution.lower()  # 保存这一项数据，后面的流程会继续使用。
        return payload  # 把结果交回调用者，这就是本步的反馈。

    async def readImages(self, response: dict, taskID: str | None = None) -> tuple[list[bytes] | None, str | None]:  # 定义一个需要等待网络或文件的异步动作。
        """从 Jimeng2API 响应 data 数组读取图片。"""
        if response is None:  # 先判断这个情况，避免后面流程出错。
            return None, "响应为空"  # 把结果交回调用者，这就是本步的反馈。
        if "data" not in response:  # 先判断这个情况，避免后面流程出错。
            return None, f"响应中未找到 data 字段: {response}"  # 把结果交回调用者，这就是本步的反馈。
        images = []  # 保存这一项数据，后面的流程会继续使用。
        for item in response.get("data") or []:  # 逐个处理这组内容，避免漏掉任何一项。
            if "b64_json" in item:  # 先判断这个情况，避免后面流程出错。
                images.append(base64.b64decode(item["b64_json"]))  # 这一行按当前流程执行，作用见上方说明。
            elif "url" in item:  # 继续判断另一种情况，让分支读起来顺。
                async with self.getSession().get(item["url"], proxy=self.proxy, timeout=self.downloadTimeout()) as resp:  # 进入异步上下文，用完后自动收尾。
                    if resp.status == 200:  # 先判断这个情况，避免后面流程出错。
                        images.append(await resp.read())  # 这一行按当前流程执行，作用见上方说明。
                    else:  # 前面情况都不符合时，走这个备用分支。
                        logger.error(f"{self.logPrefix(taskID)} 下载图像失败 ({resp.status}): {item['url']}")  # 这一行按当前流程执行，作用见上方说明。
        return (images, None) if images else (None, "未找到有效的图片数据")  # 把结果交回调用者，这就是本步的反馈。

    async def receiveToken(self) -> dict[str, Any]:  # 定义一个需要等待网络或文件的异步动作。
        """为配置里的所有 Jimeng API Key 领取积分；后台任务每天调用。"""
        if not self.apiKeys:  # 先判断这个情况，避免后面流程出错。
            return {"error": "未配置 API Key"}  # 把结果交回调用者，这就是本步的反馈。

        results: dict[str, Any] = {}  # 保存这一项数据，后面的流程会继续使用。
        url = f"{(self.baseURL or 'http://localhost:5100').rstrip('/')}/token/receive"  # 保存这一项数据，后面的流程会继续使用。
        for index, key in enumerate(self.apiKeys):  # 逐个处理这组内容，避免漏掉任何一项。
            try:  # 尝试执行可能失败的外部操作。
                async with self.getSession().post(url, headers={"Authorization": f"Bearer {key}"}, proxy=self.proxy, timeout=self.downloadTimeout()) as response:  # 进入异步上下文，用完后自动收尾。
                    responseJSON = await response.json()  # 保存这一项数据，后面的流程会继续使用。
                    results[f"key_{index}"] = {"status": response.status, "data": responseJSON}  # 保存这一项数据，后面的流程会继续使用。
                    if response.status == 200:  # 先判断这个情况，避免后面流程出错。
                        logger.info(f"{self.logPrefix()} API Key (索引 {index}) 积分领取成功: {responseJSON}")  # 这一行按当前流程执行，作用见上方说明。
                    else:  # 前面情况都不符合时，走这个备用分支。
                        logger.warning(f"{self.logPrefix()} API Key (索引 {index}) 积分领取失败 ({response.status}): {responseJSON}")  # 这一行按当前流程执行，作用见上方说明。
            except Exception as exc:  # noqa: BLE001
                logger.error(f"{self.logPrefix()} API Key (索引 {index}) 积分领取请求异常: {exc}")  # 这一行按当前流程执行，作用见上方说明。
                results[f"key_{index}"] = {"error": str(exc)}  # 保存这一项数据，后面的流程会继续使用。
        return results  # 把结果交回调用者，这就是本步的反馈。
