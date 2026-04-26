"""
这个文件只用来手动测试 OpenAI 生图接口。

它不会启动 AstrBot，也不会调用 main.py。它只做两件事：
1. 用 provider/openAI.py 测试文生图。
2. 如果 .env 里填了 REFERENCE_IMAGE，就用同一个 OpenAI 适配器测试图生图。

使用方法：
1. 复制 .env.example 为 .env，再把 OPENAI_API_KEY 填成真实 Key。
2. 想测图生图，就把 REFERENCE_IMAGE 填成本地图片路径。
3. 在本目录执行 python test.py。
4. 生成结果会保存到 testOutput 文件夹。
"""

from __future__ import annotations  # 让类型写法在 Python 3.10 里更稳定。

import asyncio  # 用来运行异步 OpenAI 请求。
import os  # 用来读取环境变量。
import sys  # 用来调整导入路径和放入 AstrBot 测试替身。
import types  # 用来创建很小的假模块。
from pathlib import Path  # 用来处理路径，比字符串拼路径更稳。


workspaceDir = Path(__file__).resolve().parent  # 当前插件目录，也就是 test.py 所在目录。
packageParentDir = workspaceDir.parent  # 导入本插件包时，需要把上一层目录放进 sys.path。
outputDir = workspaceDir / "testOutput"  # 测试图片统一输出到这里，避免弄乱项目根目录。


class TestLogger:
    """给测试脚本用的最小日志对象；只模仿 astrbot.api.logger 的常用方法。"""

    def info(self, message: str) -> None:  # 普通进度日志。
        print(f"[INFO] {message}")  # 直接打印，方便在终端看请求进度。

    def warning(self, message: str) -> None:  # 警告日志。
        print(f"[WARN] {message}")  # 直接打印，方便发现配置问题。

    def error(self, message: str) -> None:  # 错误日志。
        print(f"[ERROR] {message}")  # 直接打印，方便复制错误排查。

    def debug(self, message: str) -> None:  # 调试日志。
        print(f"[DEBUG] {message}")  # 直接打印，测试时多一点信息更好查。


class FakeAstrBotConfig(dict):
    """data.py 只需要这个名字能被导入；测试 OpenAI provider 时不会真正使用它。"""


def installAstrBotTestStub() -> None:
    """给没有 AstrBot 的本地测试环境补最小替身，让 provider/openAI.py 可以导入。"""
    astrbotModule = types.ModuleType("astrbot")  # 创建 astrbot 根模块。
    apiModule = types.ModuleType("astrbot.api")  # 创建 astrbot.api 模块。
    coreModule = types.ModuleType("astrbot.core")  # 创建 astrbot.core 模块。
    configModule = types.ModuleType("astrbot.core.config")  # 创建 astrbot.core.config 模块。
    astrbotConfigModule = types.ModuleType("astrbot.core.config.astrbot_config")  # 创建配置模块。
    apiModule.logger = TestLogger()  # provider 里只用 logger，所以这里放测试日志对象。
    astrbotConfigModule.AstrBotConfig = FakeAstrBotConfig  # data.py 导入这个名字，测试时给一个字典类即可。
    sys.modules.setdefault("astrbot", astrbotModule)  # 如果环境里没有 AstrBot，就使用这个替身。
    sys.modules.setdefault("astrbot.api", apiModule)  # 注册 astrbot.api。
    sys.modules.setdefault("astrbot.core", coreModule)  # 注册 astrbot.core。
    sys.modules.setdefault("astrbot.core.config", configModule)  # 注册 astrbot.core.config。
    sys.modules.setdefault("astrbot.core.config.astrbot_config", astrbotConfigModule)  # 注册 AstrBotConfig 所在模块。


def loadEnvFile(envPath: Path) -> None:
    """读取 .env 文件；只支持 KEY=VALUE 这种最简单、最清楚的写法。"""
    if not envPath.exists():  # 没有 .env 就提示用户先创建。
        raise FileNotFoundError(f"没有找到 {envPath}，请先复制 .env.example 为 .env。")  # 直接停止，避免拿空 Key 请求。

    for line in envPath.read_text(encoding="utf-8").splitlines():  # 一行一行读取配置。
        text = line.strip()  # 去掉首尾空格，减少手写配置出错。
        if not text or text.startswith("#"):  # 空行和注释行不是配置。
            continue  # 跳过这行，继续读下一行。
        if "=" not in text:  # 没有等号就不是有效配置。
            continue  # 跳过无效行，保持 .env 宽容。
        key, value = text.split("=", 1)  # 只按第一个等号切开，提示词里可以继续写等号。
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))  # 不覆盖系统里已有的同名环境变量。


def requireEnv(name: str) -> str:
    """读取必填环境变量；没填就给出清楚错误。"""
    value = os.environ.get(name, "").strip()  # 从系统环境或 .env 里读值。
    if not value or value == "sk-your-openai-key":  # Key 为空或还是模板值都不能请求。
        raise RuntimeError(f"请在 .env 里填写 {name}。")  # 明确告诉用户缺哪一项。
    return value  # 把可用配置交回调用者。


def readEnv(name: str, default: str | None = "") -> str | None:
    """读取可选环境变量；没填时使用默认值。"""
    value = os.environ.get(name)  # 先只读真实环境变量，避免 None 默认值被拿去 strip。
    if value is None:  # 没有配置时使用调用者给的默认值。
        return default  # 允许默认值是 None，比如 proxy 不需要时就是 None。
    return value.strip() or default  # 空字符串也按默认值处理。


def readSwitch(name: str, default: bool) -> bool:
    """读取 true/false 开关；.env 里写 false、0、no 都表示关闭。"""
    value = str(readEnv(name, "true" if default else "false")).lower()  # 统一转小写，避免 True/FALSE 这类大小写差异。
    return value not in {"false", "0", "no", "off", "关闭"}  # 只把明确的关闭词当作 False。


def makeProvider():
    """创建 OpenAI provider；这里直接测 provider，不经过 AstrBot main.py。"""
    sys.path.insert(0, str(packageParentDir))  # 让 Python 能按包名导入当前插件。
    from astrbot_plugin_super_draw.data import ProviderConfig, ProviderType  # 导入插件里的数据结构。
    from astrbot_plugin_super_draw.provider.openAI import OpenAI  # 导入这次要测试的 OpenAI 适配器。

    config = ProviderConfig(  # 组装一个最小 OpenAI 配置。
        type=ProviderType.openAI,  # 指明这是 OpenAI 供应商。
        name="OpenAITest",  # 测试用名字，只会出现在日志里。
        baseURL=readEnv("OPENAI_BASE_URL", "https://api.openai.com"),  # 支持官方地址或中转地址。
        apiKeys=[requireEnv("OPENAI_API_KEY")],  # 测试只需要一个 Key。
        model=readEnv("OPENAI_MODEL", "gpt-image-2"),  # 默认使用 gpt-image-2。
        availableModels=[readEnv("OPENAI_MODEL", "gpt-image-2")],  # 保留可用模型列表，方便日志理解。
        proxy=readEnv("OPENAI_PROXY", None),  # 如果你系统环境里有代理，也可以用 OPENAI_PROXY。
        timeout=int(readEnv("OPENAI_TIMEOUT", "180")),  # 生图可能比较慢，默认等 180 秒。
        maxRetryTimes=1,  # 测试脚本默认不轮换重试，失败时直接看真实错误。
    )
    return OpenAI(config)  # 返回真实 OpenAI provider。


def makeTextRequest():
    """创建文生图请求。"""
    from astrbot_plugin_super_draw.data import ImageRequest  # 导入统一请求对象。

    return ImageRequest(  # 用插件正式使用的数据结构来测试。
        prompt=readEnv("TEXT_PROMPT", "一只白色小猫坐在木桌旁看雨"),  # 文生图提示词。
        aspectRatio=readEnv("ASPECT_RATIO", "1:1"),  # 图片比例。
        resolution=readEnv("RESOLUTION", "1K"),  # 图片清晰度。
        taskID="test_text",  # 日志里用这个任务名。
    )


async def makeImageRequest():
    """创建图生图请求；没有 REFERENCE_IMAGE 时返回 None，让脚本跳过图生图。"""
    from astrbot_plugin_super_draw.data import ImageRequest  # 导入统一请求对象。
    from astrbot_plugin_super_draw.tool.picture import convertPicture, detectMimeType  # 使用项目自己的图片处理工具。

    imagePathText = readEnv("REFERENCE_IMAGE", "")  # 从 .env 读取参考图路径。
    if not imagePathText:  # 用户没填参考图时不测图生图。
        return None  # 返回 None 表示跳过。

    imagePath = Path(imagePathText).expanduser()  # 支持用户写 ~ 作为用户目录。
    if not imagePath.is_absolute():  # 相对路径按插件目录理解。
        imagePath = workspaceDir / imagePath  # 拼成完整路径，避免工作目录不同导致找不到文件。
    if not imagePath.exists():  # 路径不存在时给清楚错误。
        raise FileNotFoundError(f"REFERENCE_IMAGE 指向的图片不存在：{imagePath}")  # 停止测试，避免发空图片。

    imageBytes = imagePath.read_bytes()  # 读取参考图原始字节。
    mimeType = detectMimeType(imageBytes)  # 用项目自己的工具识别图片格式。
    picture = await convertPicture(imageBytes, mimeType)  # 必要时把图片转成供应商更容易接受的格式。
    return ImageRequest(  # 组装图生图请求。
        prompt=readEnv("IMAGE_PROMPT", "把参考图改成温暖的插画风头像"),  # 图生图提示词。
        images=[picture],  # 参考图列表。
        aspectRatio=readEnv("ASPECT_RATIO", "1:1"),  # 图片比例。
        resolution=readEnv("RESOLUTION", "1K"),  # 图片清晰度。
        taskID="test_image",  # 日志里用这个任务名。
    )


def saveImages(prefix: str, images: list[bytes]) -> None:
    """把 OpenAI 返回的图片保存到 testOutput 文件夹。"""
    outputDir.mkdir(exist_ok=True)  # 没有输出目录就创建。
    for index, imageBytes in enumerate(images, 1):  # 逐张保存，避免多图时覆盖。
        path = outputDir / f"{prefix}_{index}.png"  # 默认用 png 后缀，方便打开查看。
        path.write_bytes(imageBytes)  # 把图片字节写到文件。
        print(f"[OK] 已保存：{path}")  # 告诉用户结果在哪里。


async def runTextToImage(provider) -> None:
    """测试 OpenAI 文生图。"""
    print("[TEST] 开始测试文生图")  # 打印当前测试阶段。
    result = await provider.generate(makeTextRequest())  # 直接调用 provider 的统一生成入口。
    if result.error:  # 如果 provider 返回错误，就停止并显示原因。
        raise RuntimeError(f"文生图失败：{result.error}")  # 把错误抛出来，终端能看到完整失败原因。
    saveImages("textToImage", result.images or [])  # 保存文生图结果。


async def runImageToImage(provider) -> None:
    """测试 OpenAI 图生图；没有参考图时跳过。"""
    request = await makeImageRequest()  # 读取并转换参考图。
    if request is None:  # 没有参考图时不测。
        print("[SKIP] .env 没有填写 REFERENCE_IMAGE，已跳过图生图测试。")  # 清楚说明跳过原因。
        return  # 结束图生图测试。

    print("[TEST] 开始测试图生图")  # 打印当前测试阶段。
    result = await provider.generate(request)  # 有图片的请求会自动走 OpenAI edits 接口。
    if result.error:  # 如果 provider 返回错误，就停止并显示原因。
        raise RuntimeError(f"图生图失败：{result.error}")  # 把错误抛出来，终端能看到完整失败原因。
    saveImages("imageToImage", result.images or [])  # 保存图生图结果。


async def main() -> None:
    """测试脚本入口；按文生图、图生图的顺序执行。"""
    installAstrBotTestStub()  # 没有 AstrBot 环境时也能导入 provider。
    loadEnvFile(workspaceDir / ".env")  # 读取本目录下的 .env。
    provider = makeProvider()  # 创建 OpenAI provider。
    try:  # provider 里有 aiohttp 会话，用完要关闭。
        if readSwitch("RUN_TEXT_TO_IMAGE", True):  # 开关打开时才测试文生图。
            await runTextToImage(provider)  # 先测试文生图。
        if readSwitch("RUN_IMAGE_TO_IMAGE", True):  # 开关打开时才测试图生图。
            await runImageToImage(provider)  # 再测试图生图。
    finally:  # 不管成功失败，都关闭网络会话。
        await provider.close()  # 关闭 aiohttp session，避免终端提示未关闭连接。


if __name__ == "__main__":  # 只有直接运行 python test.py 时才执行。
    asyncio.run(main())  # 启动异步测试流程。
