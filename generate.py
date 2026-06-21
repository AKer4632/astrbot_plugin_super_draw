"""
通用生图引擎，与 AstrBot 完全解耦。

提供统一的 `GenerateEngine.generate()` 入口，内部根据 provider 类型分发到对应适配器：
- OpenAIAdapter：兼容 OpenAI /images/generate 与 /images/edit
- GeminiAdapter：兼容 Google Gemini 官方生图接口

支持多 provider 故障转移、API Key 轮询、统一尺寸/质量语义。
"""

from __future__ import annotations

import asyncio
import base64
from abc import ABC, abstractmethod
from typing import Any

from openai import AsyncOpenAI

try:
    from .tool.picture import detectMimeType
except ImportError:  # pragma: no cover
    from tool.picture import detectMimeType

try:
    from google import genai
    from google.genai import types as genaiTypes
except ImportError:  # pragma: no cover
    genai = None
    genaiTypes = None


class Provider:
    """一个生图 provider 的运行时配置。"""

    __slots__ = ("name", "api_type", "base_url", "api_keys", "model", "timeout", "max_retry")

    def __init__(
        self,
        name: str,
        api_type: str,
        api_keys: list[str],
        model: str,
        base_url: str = "",
        timeout: int = 180,
        max_retry: int = 3,
    ):
        self.name = name
        self.api_type = api_type
        self.api_keys = api_keys
        self.model = model
        self.base_url = (base_url or "https://api.openai.com").rstrip("/")
        self.timeout = timeout
        self.max_retry = max(1, max_retry)


class Adapter(ABC):
    """生图适配器基类。"""

    def __init__(self, provider: Provider):
        self.provider = provider
        self._client: Any = None
        self._key_index = 0

    @abstractmethod
    async def generate(self, prompt: str, images: list[bytes], size: str, quality: str, n: int) -> list[bytes]:
        """生成图片，返回 bytes 列表。"""

    def _current_key(self) -> str:
        return self.provider.api_keys[self._key_index % len(self.provider.api_keys)]

    def _rotate_key(self) -> None:
        if len(self.provider.api_keys) > 1:
            self._key_index = (self._key_index + 1) % len(self.provider.api_keys)
        self._client = None

    async def close(self) -> None:
        if self._client is not None:
            if hasattr(self._client, "close"):
                await self._client.close()
            elif hasattr(self._client, "aio") and hasattr(self._client.aio, "aclose"):
                await self._client.aio.aclose()
            self._client = None


class OpenAIAdapter(Adapter):
    """OpenAI 兼容接口适配器。"""

    _VALID_QUALITIES = {"low", "medium", "high", "auto"}
    _VALID_SIZES = {"1024x1024", "1536x1024", "1024x1536"}

    async def generate(self, prompt: str, images: list[bytes], size: str, quality: str, n: int) -> list[bytes]:
        last_error = "生成失败"
        for _ in range(self.provider.max_retry):
            try:
                client = self._get_client()
                kwargs = {
                    "model": self.provider.model,
                    "prompt": prompt,
                    "n": min(max(1, n), 4),
                    "size": self._resolve_size(size),
                }
                if quality in self._VALID_QUALITIES and quality != "auto":
                    kwargs["quality"] = quality
                if images:
                    kwargs["image"] = [(f"ref_{i}.png", img, detectMimeType(img)) for i, img in enumerate(images[:16])]
                    response = await client.images.edit(**kwargs)
                else:
                    response = await client.images.generate(**kwargs)
                return self._extract(response)
            except Exception as exc:
                last_error = str(exc)
                self._rotate_key()
        raise RuntimeError(f"OpenAI 适配器重试 {self.provider.max_retry} 次后失败: {last_error}")

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._current_key(),
                base_url=f"{self.provider.base_url}/v1",
                timeout=self.provider.timeout,
                max_retries=0,
            )
        return self._client

    @staticmethod
    def _resolve_size(size: str) -> str:
        if size in OpenAIAdapter._VALID_SIZES:
            return size
        return "1024x1024"

    @staticmethod
    def _extract(response: Any) -> list[bytes]:
        result = []
        for item in response.data or []:
            if getattr(item, "b64_json", None):
                result.append(base64.b64decode(item.b64_json))
        if not result:
            raise ValueError("响应中未找到有效图片数据")
        return result


class GeminiAdapter(Adapter):
    """Google Gemini 官方接口适配器。"""

    _RATIO_MAP = {
        "1024x1024": "1:1",
        "1536x1024": "16:9",
        "1024x1536": "9:16",
        "1:1": "1:1",
        "16:9": "16:9",
        "9:16": "9:16",
        "3:2": "3:2",
        "2:3": "2:3",
    }

    async def generate(self, prompt: str, images: list[bytes], size: str, quality: str, n: int) -> list[bytes]:
        if genaiTypes is None or genai is None:
            raise RuntimeError("缺少 google-genai 依赖")
        last_error = "生成失败"
        for _ in range(self.provider.max_retry):
            try:
                client = self._get_client()
                contents = self._build_contents(prompt, images)
                config = genaiTypes.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"])
                ratio = self._RATIO_MAP.get(size)
                if ratio:
                    config.image_config = genaiTypes.ImageConfig(aspect_ratio=ratio)
                imgs: list[bytes] = []
                for _ in range(min(max(1, n), 4)):
                    response = await client.aio.models.generate_content(
                        model=self.provider.model,
                        contents=contents,
                        config=config,
                    )
                    imgs.extend(self._extract(response))
                return imgs
            except Exception as exc:
                last_error = str(exc)
                self._rotate_key()
        raise RuntimeError(f"Gemini 适配器重试 {self.provider.max_retry} 次后失败: {last_error}")

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = genai.Client(api_key=self._current_key())
        return self._client

    def _build_contents(self, prompt: str, images: list[bytes]) -> list[Any]:
        parts: list[Any] = [genaiTypes.Part.from_text(text=prompt)]
        for img in images[:16]:
            mime = detectMimeType(img)
            if mime.startswith("image/"):
                parts.append(genaiTypes.Part.from_bytes(data=img, mime_type=mime))
        return parts

    @staticmethod
    def _extract(response: Any) -> list[bytes]:
        result = []
        for part in getattr(response, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            data = getattr(inline, "data", None) if inline else None
            if isinstance(data, bytes):
                result.append(data)
            elif isinstance(data, str):
                result.append(base64.b64decode(data))
        if not result:
            raise ValueError("Gemini 响应中未找到图片数据")
        return result


class GenerateEngine:
    """统一生图引擎：负责 provider 选择、故障转移与资源释放。"""

    def __init__(self, providers: list[Provider], current: int = 0):
        self.providers = providers
        self.current_index = current
        self._adapters: dict[int, Adapter] = {}

    async def generate(
        self,
        prompt: str,
        images: list[bytes] | None = None,
        size: str = "auto",
        quality: str = "auto",
        n: int = 1,
    ) -> list[bytes]:
        if not self.providers:
            raise ValueError("未配置生图 provider")
        images = images or []
        providers = self.providers[self.current_index :] + self.providers[: self.current_index]
        last_error = "生成失败"
        for provider in providers:
            adapter = self._adapter_for(provider)
            try:
                return await adapter.generate(prompt, images, size, quality, n)
            except Exception as exc:
                last_error = str(exc)
                continue
        raise RuntimeError(f"所有 provider 均失败: {last_error}")

    def _adapter_for(self, provider: Provider) -> Adapter:
        key = id(provider)
        if key not in self._adapters:
            self._adapters[key] = OpenAIAdapter(provider) if provider.api_type == "openai" else GeminiAdapter(provider)
        return self._adapters[key]

    async def close(self) -> None:
        await asyncio.gather(*(adapter.close() for adapter in self._adapters.values()), return_exceptions=True)
        self._adapters.clear()
