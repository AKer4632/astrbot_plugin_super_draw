"""
这个文件只测试真实生图功能，不做离线测试，不查模型列表，不手动改任何配置。

它严格读取 .env 中的配置，然后连续执行两步：
第一步：文生图，把结果保存成 test_output/text_to_image.png。
第二步：读取刚刚生成的 test_output/text_to_image.png，当作参考图继续图生图，保存成 test_output/image_to_image.png。

调用示例：
uv run python test.py

.env 必须提供这些配置：
OPENAI_API_KEY=你的 Key
OPENAI_BASE_URL=你的 OpenAI 兼容接口地址
OPENAI_MODEL=你的生图模型
TEXT_PROMPT=文生图提示词
IMAGE_PROMPT=图生图提示词
ASPECT_RATIO=1:1
RESOLUTION=1K
"""

from __future__ import annotations

import asyncio
from pathlib import Path

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
    print(f"OPENAI_BASE_URL={settings['baseURL']}")
    print(f"OPENAI_MODEL={settings['model']}")
    print(f"ASPECT_RATIO={settings['aspectRatio']} -> size={settings['size']}")
    print(f"RESOLUTION={settings['resolution']} -> quality={settings['quality']}")

    generator = ImageGenerator(
        apiKeys=settings["apiKeys"],
        baseURL=settings["baseURL"],
        model=settings["model"],
        proxy=settings["proxy"],
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
    apiKeys = readApiKeys(config)
    require(apiKeys, "OPENAI_API_KEY 或 OPENAI_API_KEYS")

    aspectRatio = requireText(config, "ASPECT_RATIO")
    resolution = requireText(config, "RESOLUTION")

    return {
        "apiKeys": apiKeys,
        "baseURL": requireText(config, "OPENAI_BASE_URL"),
        "model": requireText(config, "OPENAI_MODEL"),
        "proxy": config.get("OPENAI_PROXY") or None,
        "timeout": readInt(config, "TIMEOUT", 180),
        "maxRetry": readInt(config, "MAX_RETRY", 3),
        "textPrompt": requireText(config, "TEXT_PROMPT"),
        "imagePrompt": requireText(config, "IMAGE_PROMPT"),
        "aspectRatio": aspectRatio,
        "resolution": resolution,
        "size": mapAspectRatio(aspectRatio),
        "quality": mapResolution(resolution),
    }


def readApiKeys(config: dict[str, str]) -> list[str]:
    """读取 OPENAI_API_KEY 或 OPENAI_API_KEYS，多个 Key 用英文逗号分隔。"""
    rawText = config.get("OPENAI_API_KEYS") or config.get("OPENAI_API_KEY") or ""
    return [key.strip() for key in rawText.split(",") if key.strip()]


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


def mapAspectRatio(ratio: str) -> str:
    """把 .env 的 ASPECT_RATIO 映射成生图接口需要的 size。"""
    sizeMap = {
        "auto": "auto",
        "自动": "auto",
        "1:1": "1024x1024",
        "3:2": "1536x1024",
        "16:9": "1536x1024",
        "4:3": "1536x1024",
        "5:4": "1536x1024",
        "21:9": "1536x1024",
        "2:3": "1024x1536",
        "9:16": "1024x1536",
        "3:4": "1024x1536",
        "4:5": "1024x1536",
        "1024x1024": "1024x1024",
        "1536x1024": "1536x1024",
        "1024x1536": "1024x1536",
    }
    return sizeMap.get(ratio, ratio)


def mapResolution(resolution: str) -> str:
    """把 .env 的 RESOLUTION 映射成生图接口需要的 quality。"""
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
