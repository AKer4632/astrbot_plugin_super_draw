"""
通用生图库，与 AstrBot 完全无关，拿到别的项目里也能直接用。

这个文件统一适配两类生图接口：
OpenAI 兼容接口使用 openai.AsyncOpenAI，走 images.generate 和 images.edit。
Gemini 官方接口使用 google-genai，走 models.generate_content，并从 inline_data 里取图片。

调用示例：
gen = ImageGenerator(apiKeys=["sk-xxx"], apiType="openai", baseURL="https://api.openai.com", model="gpt-image-2")
images = await gen.generate("画一只猫", size="1024x1024", quality="high")
images = await gen.generate("把背景换成海边", images=[catBytes], size="auto", quality="auto")
gemini = ImageGenerator(apiKeys=["AIza..."], apiType="gemini", model="gemini-2.5-flash-image-preview")
images = await gemini.generate("画一只猫", size="16:9")
await gen.close()
"""

from __future__ import annotations

# base64 只服务 OpenAI 响应解码；Any 用来兼容两个 SDK 不同的响应对象类型。
import base64
from typing import Any

# OpenAI SDK 负责 OpenAI 兼容接口；Gemini SDK 在下面按需导入，没安装时不影响 OpenAI 模式。
from openai import AsyncOpenAI

try:
    from .tool.picture import detectMimeType
except ImportError:  # 允许 test.py 直接运行；插件运行时会走上面的相对导入
    from tool.picture import detectMimeType

try:
    from google import genai
    from google.genai import types as genaiTypes
except ImportError:  # pragma: no cover - 没装 Gemini 依赖时，OpenAI 模式仍然可以正常用
    genai = None
    genaiTypes = None


class ImageGenerator:
    """
    通用图片生成器。
    用 apiType 决定调用 OpenAI 兼容接口还是 Gemini 官方接口。
    失败时轮换 API Key 重试，异常直接抛出由调用方处理。
    """

    def __init__(
        self,
        apiKeys: list[str],
        baseURL: str = "",
        model: str = "gpt-image-2",
        timeout: int = 180,
        maxRetry: int = 3,
        apiType: str = "openai",
    ):
        self.apiKeys = apiKeys  # API Key 列表，支持多个轮换
        self.apiType = apiType or "openai"  # 接口类型：openai 或 gemini
        self.baseURL = (baseURL or "https://api.openai.com").rstrip("/")  # OpenAI 兼容接口地址
        self.model = model or "gpt-image-2"  # 模型名
        self.timeout = timeout  # 请求超时秒数
        self.maxRetry = max(1, maxRetry)  # 最大重试次数，至少试 1 次
        self.currentKeyIndex = 0  # 当前使用的 Key 索引
        self._openaiClient: AsyncOpenAI | None = None  # OpenAI SDK 客户端实例
        self._geminiClient: Any = None  # Gemini SDK 同步客户端，异步调用通过 .aio 完成

    async def generate(
        self,
        prompt: str,
        images: list[bytes] | None = None,
        size: str = "auto",
        quality: str = "auto",
    ) -> list[bytes]:
        """
        生成图片，返回图片字节列表。
        prompt 是提示词；images 有值时代表参考图；size 是尺寸或比例；quality 目前只传给 OpenAI。
        Gemini 官方接口没有 OpenAI quality 参数，所以 Gemini 模式会自动忽略 quality。
        """
        if not self.apiKeys:
            raise ValueError("未配置 API Key")

        lastError = "生成失败"  # 保存最后一次错误，重试结束后给用户看真实原因
        for _ in range(self.maxRetry):
            try:
                if self.apiType == "gemini":
                    return await self._geminiGenerate(prompt, images or [], size)  # Gemini 文生图和图生图都走同一个入口
                if images:
                    return await self._openaiEdit(prompt, images, size, quality)  # OpenAI 有参考图时走 edit
                return await self._openaiTextToImage(prompt, size, quality)  # OpenAI 没参考图时走 generate
            except Exception as exc:
                lastError = str(exc)
                self._rotateKey()  # 失败后切换下一个 Key，并清掉旧客户端

        raise RuntimeError(f"重试 {self.maxRetry} 次后失败: {lastError}")

    async def setConfig(self, apiKeys: list[str], baseURL: str, model: str, apiType: str = "openai") -> None:
        """
        切换生图供应商和模型。
        先关闭旧客户端，再换成新的 API Key、接口类型、接口地址和模型名，下一次生图会自动创建新客户端。
        """
        await self.close()
        self.apiKeys = apiKeys
        self.apiType = apiType or "openai"
        self.baseURL = (baseURL or "https://api.openai.com").rstrip("/")
        self.model = model or ("gemini-2.5-flash-image-preview" if self.apiType == "gemini" else "gpt-image-2")
        self.currentKeyIndex = 0

    async def close(self):
        """关闭 HTTP 客户端，释放连接池。"""
        if self._openaiClient:
            await self._openaiClient.close()
            self._openaiClient = None
        if self._geminiClient:
            await self._geminiClient.aio.aclose()
            self._geminiClient = None

    async def _openaiTextToImage(self, prompt: str, size: str, quality: str) -> list[bytes]:
        """OpenAI 文生图：调用 images.generate。"""
        client = self._getOpenAIClient()
        response = await client.images.generate(
            model=self.model,
            prompt=prompt,
            n=1,
            size=self._resolveOpenAISize(size),
            quality=quality,
        )
        return self._extractOpenAIImages(response)

    async def _openaiEdit(self, prompt: str, images: list[bytes], size: str, quality: str) -> list[bytes]:
        """OpenAI 图生图：调用 images.edit，把参考图作为输入。"""
        client = self._getOpenAIClient()
        imageFiles = [(f"ref_{i}.png", img, detectMimeType(img)) for i, img in enumerate(images[:16])]
        response = await client.images.edit(
            model=self.model,
            image=imageFiles,
            prompt=prompt,
            n=1,
            size=self._resolveOpenAISize(size),
            quality=quality,
        )
        return self._extractOpenAIImages(response)

    async def _geminiGenerate(self, prompt: str, images: list[bytes], size: str) -> list[bytes]:
        """
        Gemini 生图：把文本和参考图一起发给 models.generate_content。
        response_modalities=["TEXT", "IMAGE"] 是官方示例里的稳定写法；模型可能同时回文字说明和图片，这里只取图片。
        """
        if genaiTypes is None:
            raise RuntimeError("缺少 google-genai 依赖，请先安装 requirements.txt。")

        client = self._getGeminiClient()  # 官方客户端从这里取，Key 轮换后会自动重建
        contents = self._buildGeminiContents(prompt, images)  # 文本和参考图显式放进同一个请求
        config = genaiTypes.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"])  # 允许模型回文字，但后面只提取图片
        aspectRatio = self._mapOpenAISizeToGeminiRatio(size)  # 插件内部 size 统一映射到 Gemini 宽高比
        if aspectRatio:
            config.image_config = genaiTypes.ImageConfig(aspect_ratio=aspectRatio)

        response = await client.aio.models.generate_content(model=self.model, contents=contents, config=config)
        return self._extractGeminiImages(response)

    def _buildGeminiContents(self, prompt: str, images: list[bytes]) -> list[Any]:
        """把提示词和参考图整理成 Gemini SDK 可以理解的 Part 列表。"""
        if genaiTypes is None:
            return [prompt]

        parts: list[Any] = [genaiTypes.Part.from_text(text=prompt)]  # 第一段永远是文字提示词，模型先读任务目标
        for imageBytes in images[:16]:
            mimeType = detectMimeType(imageBytes)  # 根据文件头判断格式，比相信扩展名更安全
            if not mimeType.startswith("image/"):
                continue
            parts.append(genaiTypes.Part.from_bytes(data=imageBytes, mime_type=mimeType))  # 参考图按字节直接传入
        return parts

    def _extractOpenAIImages(self, response: Any) -> list[bytes]:
        """从 OpenAI SDK 响应中提取 base64 图片并解码成字节。"""
        result: list[bytes] = []
        for item in response.data:
            if item.b64_json:
                result.append(base64.b64decode(item.b64_json))
        if not result:
            raise ValueError("响应中未找到有效图片数据")
        return result

    def _extractGeminiImages(self, response: Any) -> list[bytes]:
        """从 Gemini 响应中提取 inline_data 图片字节。"""
        result: list[bytes] = []
        for part in getattr(response, "parts", []) or []:
            inlineData = getattr(part, "inline_data", None)  # Gemini 图片通常放在 part.inline_data.data
            imageData = getattr(inlineData, "data", None) if inlineData else None
            if isinstance(imageData, bytes):
                result.append(imageData)  # 新版 google-genai 通常已经给 bytes，可以直接保存
            elif isinstance(imageData, str):
                result.append(base64.b64decode(imageData))  # 兼容少数场景返回 base64 字符串
        if not result:
            raise ValueError("Gemini 响应中未找到图片数据，请确认模型支持图片输出。")
        return result

    def _getOpenAIClient(self) -> AsyncOpenAI:
        """获取或创建 AsyncOpenAI 客户端；Key 轮换后会重建。"""
        if self._openaiClient is None:
            self._openaiClient = AsyncOpenAI(
                api_key=self.apiKeys[self.currentKeyIndex % len(self.apiKeys)],
                base_url=f"{self.baseURL}/v1",
                timeout=self.timeout,
                max_retries=0,
            )
        return self._openaiClient

    def _getGeminiClient(self) -> Any:
        """获取或创建 Gemini 客户端；官方 SDK 的异步接口挂在 client.aio 上。"""
        if genai is None:
            raise RuntimeError("缺少 google-genai 依赖，请先安装 requirements.txt。")
        if self._geminiClient is None:
            self._geminiClient = genai.Client(api_key=self.apiKeys[self.currentKeyIndex % len(self.apiKeys)])
        return self._geminiClient

    def _rotateKey(self) -> None:
        """轮换到下一个 API Key，并销毁旧客户端让下次请求重建。"""
        if len(self.apiKeys) > 1:
            self.currentKeyIndex = (self.currentKeyIndex + 1) % len(self.apiKeys)
        self._openaiClient = None
        self._geminiClient = None

    @staticmethod
    def _resolveOpenAISize(size: str) -> str:
        """OpenAI 接口不接受 'auto'，需映射成合法尺寸。"""
        return size if size and size != "auto" else "1024x1024"

    @staticmethod
    def _mapOpenAISizeToGeminiRatio(size: str) -> str:
        """把插件内部的 OpenAI 尺寸值转成 Gemini 支持的宽高比。"""
        ratioMap = {
            "1024x1024": "1:1",
            "1536x1024": "3:2",
            "1024x1536": "2:3",
            "1:1": "1:1",
            "3:2": "3:2",
            "2:3": "2:3",
            "16:9": "16:9",
            "9:16": "9:16",
        }
        return ratioMap.get(size, "")
