"""
这个文件只测试真实生图功能，不做离线测试，不查模型列表，不手动改任何配置。

它严格读取 .env 中的配置，然后连续执行两步：
第一步：文生图，把结果保存成 test_output/text_to_image.png。
第二步：读取刚刚生成的 test_output/text_to_image.png，当作参考图继续图生图，保存成 test_output/image_to_image.png。

调用示例：
uv run python test.py
py -3 test.py

.env 可以测试 OpenAI 兼容接口，也可以测试 Gemini 官方接口：
API_TYPE=openai
OPENAI_API_KEY=你的 OpenAI Key
OPENAI_BASE_URL=你的 OpenAI 兼容接口地址
OPENAI_MODEL=你的生图模型
API_TYPE=gemini
GEMINI_API_KEY=你的 Gemini Key
GEMINI_MODEL=gemini-2.5-flash-image-preview
TEXT_PROMPT=文生图提示词
IMAGE_PROMPT=图生图提示词
ASPECT_RATIO=1:1
RESOLUTION=1K
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from data import PluginData
from generate import ImageGenerator

# 当前插件根目录，.env 和输出文件都按这个目录寻找。
rootDir = Path(__file__).parent.resolve()

# 测试配置文件，只从这里读取，不在代码里手动改接口、Key 或模型。
envFile = rootDir / ".env"

# 测试输出目录，文生图和图生图结果都保存在这里。
outputDir = rootDir / "test_output"


async def main() -> None:
    """真实生图测试入口：读取 .env，先文生图，再拿文生图结果做图生图。"""
    config = readEnv(envFile)
    settings = readSettings(config)
    outputDir.mkdir(parents=True, exist_ok=True)

    print("开始真实生图测试，只使用 .env 配置。")
    print(f"API_TYPE={settings['apiType']}")
    print(f"BASE_URL={settings['baseURL'] or '官方默认地址'}")
    print(f"MODEL={settings['model']}")
    print(f"ASPECT_RATIO={settings['aspectRatio']} -> size={settings['size']}")
    print(f"RESOLUTION={settings['resolution']} -> quality={settings['quality']}")

    generator = ImageGenerator(
        apiKeys=settings["apiKeys"],
        apiType=settings["apiType"],
        baseURL=settings["baseURL"],
        model=settings["model"],
        timeout=settings["timeout"],
        maxRetry=settings["maxRetry"],
    )

    try:
        textImage = await runTextToImage(generator, settings)
        await runImageToImage(generator, settings, textImage)
    finally:
        await generator.close()

    print("真实生图测试完成。")


async def runTextToImage(generator: ImageGenerator, settings: dict) -> Path:
    """第一步：文生图，保存模型返回的第一张图片。"""
    print("\n[1/2] 文生图开始。")
    print(f"TEXT_PROMPT={settings['textPrompt']}")

    images = await generator.generate(
        prompt=settings["textPrompt"],
        images=None,
        size=settings["size"],
        quality=settings["quality"],
    )

    if not images:
        raise RuntimeError("文生图接口成功返回了响应，但里面没有图片。")

    imagePath = outputDir / "text_to_image.png"
    imagePath.write_bytes(images[0])
    print(f"文生图成功：{imagePath}")
    print(f"文生图字节数：{len(images[0])}")
    return imagePath


async def runImageToImage(generator: ImageGenerator, settings: dict, referencePath: Path) -> Path:
    """第二步：读取第一步生成的图片，作为参考图继续图生图。"""
    print("\n[2/2] 图生图开始。")
    print(f"参考图={referencePath}")
    print(f"IMAGE_PROMPT={settings['imagePrompt']}")

    referenceImage = referencePath.read_bytes()
    images = await generator.generate(
        prompt=settings["imagePrompt"],
        images=[referenceImage],
        size=settings["size"],
        quality=settings["quality"],
    )

    if not images:
        raise RuntimeError("图生图接口成功返回了响应，但里面没有图片。")

    imagePath = outputDir / "image_to_image.png"
    imagePath.write_bytes(images[0])
    print(f"图生图成功：{imagePath}")
    print(f"图生图字节数：{len(images[0])}")
    return imagePath


def readEnv(path: Path) -> dict[str, str]:
    """读取 .env 文件，支持 KEY=value、空行和 # 注释。"""
    if not path.exists():
        raise FileNotFoundError(f"找不到 .env 文件：{path}")

    config: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        config[key.strip()] = value.strip().strip('"').strip("'")
    return config


def readSettings(config: dict[str, str]) -> dict:
    """把 .env 文本配置整理成 ImageGenerator 能直接使用的数据。"""
    apiType = readApiType(config)
    apiKeys = readApiKeys(config, apiType)
    require(apiKeys, "OPENAI_API_KEY、OPENAI_API_KEYS、GEMINI_API_KEY 或 GEMINI_API_KEYS")

    aspectRatio = requireText(config, "ASPECT_RATIO")
    resolution = requireText(config, "RESOLUTION")

    return {
        "apiType": apiType,
        "apiKeys": apiKeys,
        "baseURL": readBaseURL(config, apiType),
        "model": readModel(config, apiType),
        "timeout": readInt(config, "TIMEOUT", 180),
        "maxRetry": readInt(config, "MAX_RETRY", 3),
        "textPrompt": requireText(config, "TEXT_PROMPT"),
        "imagePrompt": requireText(config, "IMAGE_PROMPT"),
        "aspectRatio": aspectRatio,
        "resolution": resolution,
        "size": PluginData.mapAspectRatio(aspectRatio),
        "quality": mapResolution(resolution),
    }


def readApiType(config: dict[str, str]) -> str:
    """读取 API_TYPE；只接受 openai 和 gemini，避免拼错后请求走错接口。"""
    apiType = config.get("API_TYPE", "openai").strip().lower()
    if apiType not in ("openai", "gemini"):
        raise RuntimeError("API_TYPE 只能填写 openai 或 gemini。")
    return apiType


def readApiKeys(config: dict[str, str], apiType: str) -> list[str]:
    """按接口类型读取 Key；多个 Key 用英文逗号分隔。"""
    if apiType == "gemini":
        rawText = config.get("GEMINI_API_KEYS") or config.get("GEMINI_API_KEY") or config.get("OPENAI_API_KEYS") or config.get("OPENAI_API_KEY") or ""
    else:
        rawText = config.get("OPENAI_API_KEYS") or config.get("OPENAI_API_KEY") or ""
    return [key.strip() for key in rawText.split(",") if key.strip()]


def readBaseURL(config: dict[str, str], apiType: str) -> str:
    """OpenAI 兼容接口需要 Base URL；Gemini 官方接口不需要。"""
    if apiType == "gemini":
        return ""
    return requireText(config, "OPENAI_BASE_URL")


def readModel(config: dict[str, str], apiType: str) -> str:
    """按接口类型读取模型名；Gemini 未填写时使用官方生图预览模型。"""
    if apiType == "gemini":
        return config.get("GEMINI_MODEL", "gemini-2.5-flash-image-preview").strip() or "gemini-2.5-flash-image-preview"
    return requireText(config, "OPENAI_MODEL")


def requireText(config: dict[str, str], key: str) -> str:
    """读取必填文本；缺少就直接报错，避免悄悄使用代码里的默认值。"""
    value = config.get(key, "").strip()
    if not value:
        raise RuntimeError(f".env 缺少必填配置：{key}")
    return value


def require(value, name: str) -> None:
    """检查必填值；为空就报错。"""
    if not value:
        raise RuntimeError(f".env 缺少必填配置：{name}")


def readInt(config: dict[str, str], key: str, default: int) -> int:
    """读取整数配置；没写就使用默认值。"""
    if key not in config or not config[key].strip():
        return default
    return int(config[key])


def mapResolution(resolution: str) -> str:
    """把 .env 的 RESOLUTION 映射成生图接口需要的 quality（兼容 1K/2K/4K 旧写法）。"""
    qualityMap = {
        "auto": "auto",
        "自动": "auto",
        "1K": "low",
        "2K": "medium",
        "4K": "high",
        "low": "low",
        "medium": "medium",
        "high": "high",
    }
    return qualityMap.get(resolution, resolution)


if __name__ == "__main__":
    asyncio.run(main())
