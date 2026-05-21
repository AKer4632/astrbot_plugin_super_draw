"""
通用生图库，与 AstrBot 完全无关，拿到别的项目里也能直接用。

通过 OpenAI 兼容格式 API 生成图片，支持文生图和图生图。
传入 API 配置创建实例，调用 generate() 拿到图片字节列表。

调用示例：
gen = ImageGenerator(apiKeys=["sk-xxx"], baseURL="https://api.openai.com", model="gpt-image-2")
images = await gen.generate("画一只猫", size="1024x1024", quality="high")
images = await gen.generate("把背景换成海边", images=[catBytes], size="auto", quality="auto")
images = await gen.generate("赛博朋克风格城市")
await gen.close()
"""

from __future__ import annotations

import base64

from openai import AsyncOpenAI


class ImageGenerator:
    """
    通用图片生成器。
    用 OpenAI 兼容 SDK 调用 images.generate（文生图）和 images.edit（图生图）。
    失败时轮换 API Key 重试，异常直接抛出由调用方处理。
    """

    def __init__(
        self,
        apiKeys: list[str],
        baseURL: str = "",
        model: str = "gpt-image-2",
        timeout: int = 180,
        maxRetry: int = 3,
    ):
        self.apiKeys = apiKeys  # API Key 列表，支持多个轮换
        self.baseURL = (baseURL or "https://api.openai.com").rstrip("/")  # 接口地址
        self.model = model or "gpt-image-2"  # 模型名
        self.timeout = timeout  # 请求超时秒数
        self.maxRetry = max(1, maxRetry)  # 最大重试次数
        self.currentKeyIndex = 0  # 当前使用的 Key 索引
        self._client: AsyncOpenAI | None = None  # SDK 客户端实例

    async def generate(
        self,
        prompt: str,
        images: list[bytes] | None = None,
        size: str = "auto",
        quality: str = "auto",
    ) -> list[bytes]:
        """
        生成图片，返回图片字节列表。
        - prompt: 提示词
        - images: 参考图字节列表（传了走图生图，不传走文生图）
        - size: 图片尺寸，如 "auto"、"1024x1024"、"1536x1024"、"1024x1536"
        - quality: 图片质量，如 "auto"、"low"、"medium"、"high"
        - 失败时抛出 Exception，调用方自己 try-catch
        """
        if not self.apiKeys:
            raise ValueError("未配置 API Key")

        lastError = "生成失败"
        for attempt in range(self.maxRetry):
            try:
                # 有参考图走图生图，没有走文生图
                if images:
                    result = await self._edit(prompt, images, size, quality)
                else:
                    result = await self._textToImage(prompt, size, quality)
                return result
            except Exception as exc:
                lastError = str(exc)
                self._rotateKey()  # 失败后切换下一个 Key

        raise RuntimeError(f"重试 {self.maxRetry} 次后失败: {lastError}")

    async def close(self):
        """关闭 HTTP 客户端，释放连接池。"""
        if self._client:
            await self._client.close()
            self._client = None

    async def _textToImage(self, prompt: str, size: str, quality: str) -> list[bytes]:
        """文生图：调用 images.generate。"""
        client = self._getClient()
        response = await client.images.generate(
            model=self.model,
            prompt=prompt,
            n=1,
            size=size,
            quality=quality,
        )
        return self._extractImages(response)

    async def _edit(self, prompt: str, images: list[bytes], size: str, quality: str) -> list[bytes]:
        """图生图：调用 images.edit，把参考图作为输入。"""
        client = self._getClient()
        # SDK 接受 (文件名, 字节, MIME类型) 的元组列表，最多 16 张
        imageFiles = [(f"ref_{i}.png", img, "image/png") for i, img in enumerate(images[:16])]
        response = await client.images.edit(
            model=self.model,
            image=imageFiles,
            prompt=prompt,
            n=1,
            size=size,
            quality=quality,
        )
        return self._extractImages(response)

    def _extractImages(self, response) -> list[bytes]:
        """从 SDK 响应中提取 base64 图片并解码成字节。"""
        result: list[bytes] = []
        for item in response.data:
            if item.b64_json:
                result.append(base64.b64decode(item.b64_json))
        if not result:
            raise ValueError("响应中未找到有效图片数据")
        return result

    def _getClient(self) -> AsyncOpenAI:
        """获取或创建 AsyncOpenAI 客户端；Key 轮换后会重建。"""
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.apiKeys[self.currentKeyIndex % len(self.apiKeys)],
                base_url=f"{self.baseURL}/v1",
                timeout=self.timeout,
                max_retries=0,  # 重试逻辑由我们自己控制
            )
        return self._client

    def _rotateKey(self) -> None:
        """轮换到下一个 API Key，并销毁旧客户端让下次请求重建。"""
        if len(self.apiKeys) > 1:
            self.currentKeyIndex = (self.currentKeyIndex + 1) % len(self.apiKeys)
            self._client = None  # 下次 _getClient() 会用新 Key 创建
