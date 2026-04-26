"""
这个文件只写 OpenAI 怎么生图。

没有参考图时，用“文生图”接口；有参考图时，用“图生图”接口。这里尽量不用晦涩词：
form 表示要发给 OpenAI 的表单，payload 表示要发给 OpenAI 的普通 JSON 数据。
"""

from __future__ import annotations

import base64
import time
from typing import Any

import aiohttp

from astrbot.api import logger

from ..data import ImageAbility, ImageRequest
from .base import BaseProvider


class OpenAI(BaseProvider):  # 定义一组放在一起的数据或行为。
    """OpenAI 生图接口。"""

    def getAbilities(self) -> ImageAbility:  # 定义一个可重复调用的小动作。
        """告诉 image.py：OpenAI 一定支持文生图；只有 gpt-image 系列才支持图生图。"""
        abilities = ImageAbility.textToImage | ImageAbility.aspectRatio | ImageAbility.resolution  # OpenAI 文生图、比例、清晰度是基础能力。
        if self.canEditImages():  # 只有当前模型是 gpt-image 系列时，才把图生图能力暴露给命令和 LLM 工具。
            abilities = abilities | ImageAbility.imageToImage  # 把图生图能力加进去，让上层可以收参考图。
        return abilities  # 把当前模型真实支持的能力交回调用者。

    async def generateOnce(self, request: ImageRequest) -> tuple[list[bytes] | None, str | None]:  # 定义一个需要等待网络或文件的异步动作。
        """按有没有参考图，选择文生图或图生图。"""
        if request.images:  # 先判断这个情况，避免后面流程出错。
            return await self.editImages(request)  # 有参考图就是图生图。
        return await self.generateImages(request)  # 没参考图就是文生图。

    async def generateImages(self, request: ImageRequest) -> tuple[list[bytes] | None, str | None]:  # 定义一个需要等待网络或文件的异步动作。
        """文生图：把提示词发给 OpenAI，拿回图片。"""
        startTime = time.time()  # 记录开始时间，日志里要显示耗时。
        payload = self.buildTextImageJSON(request)  # 普通 JSON 数据，适合文生图接口。
        url = self.imageURL("generations")  # 文生图接口地址。
        headers = {"Authorization": f"Bearer {self.currentAPIKey()}", "Content-Type": "application/json"}  # JSON 请求需要写内容类型。
        try:  # 尝试执行可能失败的外部操作。
            async with self.getSession().post(url, json=payload, headers=headers, proxy=self.proxy, timeout=self.requestTimeout()) as response:  # 进入异步上下文，用完后自动收尾。
                duration = time.time() - startTime  # 请求耗时。
                if response.status != 200:  # 先判断这个情况，避免后面流程出错。
                    errorText = await response.text()  # OpenAI 返回的错误文本。
                    logger.error(f"{self.logPrefix(request.taskID)} API 错误 ({response.status}, 耗时: {duration:.2f}s): {errorText}")  # 这一行按当前流程执行，作用见上方说明。
                    return None, f"API 错误 ({response.status})"  # 把结果交回调用者，这就是本步的反馈。
                logger.info(f"{self.logPrefix(request.taskID)} 文生图成功 (耗时: {duration:.2f}s)")  # 这一行按当前流程执行，作用见上方说明。
                return await self.readImages(await response.json())  # 成功后从 JSON 里取图片。
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.logPrefix(request.taskID)} 文生图请求异常: {exc}")  # 这一行按当前流程执行，作用见上方说明。
            return None, str(exc)  # 把结果交回调用者，这就是本步的反馈。

    async def editImages(self, request: ImageRequest) -> tuple[list[bytes] | None, str | None]:  # 定义一个需要等待网络或文件的异步动作。
        """图生图：把参考图和提示词一起发给 OpenAI。"""
        if not self.canEditImages():  # 先判断这个情况，避免后面流程出错。
            return None, f"模型 {self.model or 'dall-e-3'} 不支持 OpenAI 图生图，请切换到 gpt-image 系列。"  # DALL-E 系列不支持这里的图生图流程。

        startTime = time.time()  # 记录开始时间。
        url = self.imageURL("edits")  # 图生图接口地址。
        headers = {"Authorization": f"Bearer {self.currentAPIKey()}"}  # 表单请求不手写 Content-Type，aiohttp 会自动补边界。
        form = self.buildEditForm(request)  # 把文字和图片放进表单。
        try:  # 尝试执行可能失败的外部操作。
            async with self.getSession().post(url, data=form, headers=headers, proxy=self.proxy, timeout=self.requestTimeout()) as response:  # 进入异步上下文，用完后自动收尾。
                duration = time.time() - startTime  # 请求耗时。
                if response.status != 200:  # 先判断这个情况，避免后面流程出错。
                    errorText = await response.text()  # 错误详情。
                    logger.error(f"{self.logPrefix(request.taskID)} 图生图 API 错误 ({response.status}, 耗时: {duration:.2f}s): {errorText}")  # 这一行按当前流程执行，作用见上方说明。
                    return None, f"API 错误 ({response.status})"  # 把结果交回调用者，这就是本步的反馈。
                logger.info(f"{self.logPrefix(request.taskID)} 图生图成功 (耗时: {duration:.2f}s，参考图: {len(request.images)}张)")  # 这一行按当前流程执行，作用见上方说明。
                return await self.readImages(await response.json())  # 成功后读取图片。
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.logPrefix(request.taskID)} 图生图请求异常: {exc}")  # 这一行按当前流程执行，作用见上方说明。
            return None, str(exc)  # 把结果交回调用者，这就是本步的反馈。

    def imageURL(self, action: str) -> str:  # 定义一个可重复调用的小动作。
        """拼出 OpenAI 图片接口地址；action 是 generations 或 edits。"""
        baseURL = self.baseURL.rstrip("/") if self.baseURL else "https://api.openai.com"  # 用户没填时用官方地址。
        return f"{baseURL}/v1/images/{action}"  # 把结果交回调用者，这就是本步的反馈。

    def buildTextImageJSON(self, request: ImageRequest) -> dict:  # 定义一个可重复调用的小动作。
        """准备文生图要发送的 JSON。"""
        isGPTImage = self.isGPTImageModel()  # GPT Image 系列和旧 DALL-E 参数不同。
        payload: dict[str, Any] = {"model": self.model or "dall-e-3", "prompt": request.prompt, "n": 1}  # 基础字段。
        size = self.mapSize(request.aspectRatio, isGPTImage)  # 把 16:9 这类比例转成 OpenAI 要的尺寸。
        quality = self.mapQuality(request.resolution, isGPTImage)  # 把 1K/2K/4K 转成 OpenAI 要的质量。
        if size:  # 先判断这个情况，避免后面流程出错。
            payload["size"] = size  # 保存这一项数据，后面的流程会继续使用。
        if quality:  # 先判断这个情况，避免后面流程出错。
            payload["quality"] = quality  # 保存这一项数据，后面的流程会继续使用。
        if not isGPTImage:  # 先判断这个情况，避免后面流程出错。
            payload["response_format"] = "b64_json"  # 旧模型需要明确要求返回 base64，方便直接发图。
        return payload  # 把结果交回调用者，这就是本步的反馈。

    def buildEditForm(self, request: ImageRequest) -> aiohttp.FormData:  # 定义一个可重复调用的小动作。
        """准备图生图要发送的表单。"""
        isGPTImage = True  # 能走到这里已经通过 canEditImages，当前模型一定是 gpt-image 系列。
        form = aiohttp.FormData()  # 表单可以同时放文字字段和图片文件。
        form.add_field("model", self.model or "gpt-image-2")  # 模型名。
        form.add_field("prompt", request.prompt)  # 提示词。
        form.add_field("n", "1")  # 当前插件一次只要一组结果。
        size = self.mapEditSize(request.aspectRatio, isGPTImage)  # 图生图尺寸。
        quality = self.mapEditQuality(request.resolution, isGPTImage)  # 图生图质量。
        if size:  # 先判断这个情况，避免后面流程出错。
            form.add_field("size", size)  # 这一行按当前流程执行，作用见上方说明。
        if quality:  # 先判断这个情况，避免后面流程出错。
            form.add_field("quality", quality)  # 这一行按当前流程执行，作用见上方说明。
        for index, image in enumerate(request.images[:16]):  # 逐个处理这组内容，避免漏掉任何一项。
            form.add_field(  # 这一行按当前流程执行，作用见上方说明。
                "image[]",  # OpenAI 多图字段；多张图就重复添加。
                image.data,  # 图片字节。
                filename=f"reference_{index}{self.extensionForMime(image.mimeType)}",  # 文件名只用于告诉接口格式。
                content_type=image.mimeType,  # 图片格式，例如 image/png。
            )  # 这一行按当前流程执行，作用见上方说明。
        return form  # 把结果交回调用者，这就是本步的反馈。

    def canEditImages(self) -> bool:  # 定义一个可重复调用的小动作。
        """判断当前模型能不能图生图。"""
        model = self.model or "gpt-image-2"  # 没填模型时按 gpt-image-2 处理。
        return model.startswith("gpt-image")  # 只有 gpt-image 系列支持 OpenAI 图生图；DALL-E 系列不走这里。

    def isGPTImageModel(self) -> bool:  # 定义一个可重复调用的小动作。
        """判断是不是 GPT Image 系列。"""
        return (self.model or "gpt-image-2").startswith("gpt-image")  # 把结果交回调用者，这就是本步的反馈。

    def mapSize(self, aspectRatio: str | None, isGPTImage: bool) -> str | None:  # 定义一个可重复调用的小动作。
        """把用户习惯的比例转成 OpenAI 的尺寸。"""
        if not aspectRatio or aspectRatio == "自动":  # 先判断这个情况，避免后面流程出错。
            return "auto" if isGPTImage else "1024x1024"  # 把结果交回调用者，这就是本步的反馈。
        if isGPTImage:  # 先判断这个情况，避免后面流程出错。
            sizeByRatio = {"1:1": "1024x1024", "3:2": "1536x1024", "16:9": "1536x1024", "4:3": "1536x1024", "5:4": "1536x1024", "21:9": "1536x1024", "2:3": "1024x1536", "3:4": "1024x1536", "9:16": "1024x1536", "4:5": "1024x1536"}  # GPT Image 支持横图、竖图、方图。
        else:  # 前面情况都不符合时，走这个备用分支。
            sizeByRatio = {"1:1": "1024x1024", "3:2": "1792x1024", "16:9": "1792x1024", "4:3": "1792x1024", "5:4": "1792x1024", "21:9": "1792x1024", "2:3": "1024x1792", "3:4": "1024x1792", "9:16": "1024x1792", "4:5": "1024x1792"}  # DALL-E 3 只有三种尺寸，尽量取接近的。
        return sizeByRatio.get(aspectRatio)  # 把结果交回调用者，这就是本步的反馈。

    def mapQuality(self, resolution: str | None, isGPTImage: bool) -> str | None:  # 定义一个可重复调用的小动作。
        """把 1K、2K、4K 转成 OpenAI 的质量参数。"""
        if not resolution:  # 先判断这个情况，避免后面流程出错。
            return None  # 把结果交回调用者，这就是本步的反馈。
        qualityByResolution = {"1K": "low", "2K": "medium", "4K": "high"} if isGPTImage else {"1K": "standard", "2K": "hd", "4K": "hd"}  # 不同模型用词不同。
        return qualityByResolution.get(resolution)  # 把结果交回调用者，这就是本步的反馈。

    def mapEditSize(self, aspectRatio: str | None, isGPTImage: bool) -> str | None:  # 定义一个可重复调用的小动作。
        """图生图尺寸；当前只服务 gpt-image 系列。"""
        if isGPTImage:  # 先判断这个情况，避免后面流程出错。
            return self.mapSize(aspectRatio, True)  # 把结果交回调用者，这就是本步的反馈。
        return None  # 备用返回；正常不会走到这里。

    def mapEditQuality(self, resolution: str | None, isGPTImage: bool) -> str | None:  # 定义一个可重复调用的小动作。
        """图生图质量；当前只服务 gpt-image 系列。"""
        if isGPTImage:  # 先判断这个情况，避免后面流程出错。
            return self.mapQuality(resolution, True)  # 把结果交回调用者，这就是本步的反馈。
        return None  # 备用返回；正常不会走到这里。

    def extensionForMime(self, mimeType: str) -> str:  # 定义一个可重复调用的小动作。
        """按图片格式给临时文件名补后缀。"""
        extensionByMime = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/webp": ".webp"}  # 常见图片格式。
        return extensionByMime.get(mimeType, ".png")  # 把结果交回调用者，这就是本步的反馈。

    async def readImages(self, response: dict) -> tuple[list[bytes] | None, str | None]:  # 定义一个需要等待网络或文件的异步动作。
        """从 OpenAI 返回结果里取图片。"""
        if "data" not in response:  # 先判断这个情况，避免后面流程出错。
            return None, "响应中未找到 data 字段"  # 把结果交回调用者，这就是本步的反馈。

        images = []  # 最后要发回用户的图片字节。
        for item in response["data"]:  # 逐个处理这组内容，避免漏掉任何一项。
            if "b64_json" in item:  # 先判断这个情况，避免后面流程出错。
                images.append(base64.b64decode(item["b64_json"]))  # base64 需要先解码成图片字节。
            elif "url" in item:  # 继续判断另一种情况，让分支读起来顺。
                async with self.getSession().get(item["url"], proxy=self.proxy, timeout=self.downloadTimeout()) as reply:  # 进入异步上下文，用完后自动收尾。
                    if reply.status == 200:  # 先判断这个情况，避免后面流程出错。
                        images.append(await reply.read())  # 有些中转站会返回 URL，这里下载回来。
        return (images, None) if images else (None, "未找到有效的图片数据")  # 把结果交回调用者，这就是本步的反馈。
