"""
这个文件只放“数据”和“读写数据的方法”。

你可以把它理解成插件的账本：这里写清楚有哪些供应商、当前用哪个模型、用户今天用了几次、
默认图片比例是多少、预设有哪些。它不负责画图，也不负责回消息。

真实调用例子：
data = ImageData(config, dataDir)
currentProvider = data.currentProvider
data.saveCurrentModel("OpenAI/gpt-image-2")
data.savePreset("手办化", "高质量手办照片")
checkResult = data.checkUserCanGenerate(event.unified_msg_origin)
"""

from __future__ import annotations

import datetime
import enum
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig


class ProviderType(str, enum.Enum):  # 定义一组放在一起的数据或行为。
    """供应商种类；等号右边的字符串来自 _conf_schema.json，不能随便改。"""

    gemini = "gemini"  # 保存这一项数据，后面的流程会继续使用。
    geminiOpenAI = "gemini_openai"  # 保存这一项数据，后面的流程会继续使用。
    openAI = "openai"  # 保存这一项数据，后面的流程会继续使用。
    zImage = "z_image_gitee"  # 保存这一项数据，后面的流程会继续使用。
    jimeng = "jimeng2api"  # 保存这一项数据，后面的流程会继续使用。
    grok = "grok"  # 保存这一项数据，后面的流程会继续使用。


class ImageAbility(enum.Flag):  # 定义一组放在一起的数据或行为。
    """供应商能力；image.py 会用它判断“能不能传参考图、能不能指定比例”。"""

    none = 0  # 保存这一项数据，后面的流程会继续使用。
    textToImage = enum.auto()  # 保存这一项数据，后面的流程会继续使用。
    imageToImage = enum.auto()  # 保存这一项数据，后面的流程会继续使用。
    resolution = enum.auto()  # 保存这一项数据，后面的流程会继续使用。
    aspectRatio = enum.auto()  # 保存这一项数据，后面的流程会继续使用。


@dataclass  # 这一行按当前流程执行，作用见上方说明。
class ProviderConfig:  # 定义一组放在一起的数据或行为。
    """一个供应商的设置；例如 OpenAI 的网址、Key、模型名都会放在这里。"""

    type: ProviderType = ProviderType.gemini  # 保存这一项数据，后面的流程会继续使用。
    name: str = ""  # 供应商显示名，例如“OpenAI 接口”。
    baseURL: str | None = None  # API 基础地址；用户不填时使用供应商默认地址。
    apiKeys: list[str] = field(default_factory=list)  # 可轮换使用的 API Key 列表。
    model: str = ""  # 当前模型名，例如 gpt-image-2。
    availableModels: list[str] = field(default_factory=list)  # 这个供应商可选择的模型名。
    proxy: str | None = None  # HTTP 代理地址；不需要代理时为 None。
    timeout: int = 180  # 请求最长等待秒数，防止生图请求一直卡住。
    maxRetryTimes: int = 3  # 失败后最多重试几次。
    safetySettings: str | None = None  # Gemini 安全设置；其他供应商通常不用。


@dataclass  # 这一行按当前流程执行，作用见上方说明。
class PictureData:  # 定义一组放在一起的数据或行为。
    """一张图片的数据；图生图时会把多张 PictureData 交给供应商。"""

    data: bytes  # 图片二进制内容，也就是文件里真正的字节。
    mimeType: str  # 图片格式，例如 image/png、image/jpeg。


@dataclass  # 这一行按当前流程执行，作用见上方说明。
class ImageRequest:  # 定义一组放在一起的数据或行为。
    """一次生图请求；image.py 创建它，provider 文件读取它。"""

    prompt: str  # 用户最终给模型的提示词。
    images: list[PictureData] = field(default_factory=list)  # 参考图列表；文生图时为空。
    aspectRatio: str | None = None  # 图片比例；None 表示不传给供应商。
    resolution: str | None = None  # 图片清晰度；None 表示不传给供应商。
    taskID: str | None = None  # 本次任务编号，用来串起日志和用户反馈。


@dataclass  # 这一行按当前流程执行，作用见上方说明。
class ImageResult:  # 定义一组放在一起的数据或行为。
    """一次生图结果；成功时 images 有图，失败时 error 有原因。"""

    images: list[bytes] | None = None  # 供应商返回的图片字节列表。
    error: str | None = None  # 失败原因；None 表示没有失败。


@dataclass  # 这一行按当前流程执行，作用见上方说明。
class UserLimit:  # 定义一组放在一起的数据或行为。
    """用户限制；防止同一个人刷太快或一天用太多。"""

    rateLimitSeconds: int = 0  # 两次请求之间至少隔几秒；0 表示不限速。
    enableDailyLimit: bool = False  # 是否开启每日次数限制。
    dailyLimitCount: int = 10  # 每人每天最多成功生成几次。
    maxImageSizeMB: int = 10  # 参考图最大多少 MB，太大会被忽略。


@dataclass  # 这一行按当前流程执行，作用见上方说明。
class CacheLimit:  # 定义一组放在一起的数据或行为。
    """缓存限制；生成图和参考图会先保存到本地 cache 文件夹。"""

    maxCacheCount: int = 100  # cache 最多保留多少个文件。
    cleanupIntervalHours: int = 24  # 每隔多少小时清理一次 cache。


@dataclass  # 这一行按当前流程执行，作用见上方说明。
class ImageDefault:  # 定义一组放在一起的数据或行为。
    """默认生图设置；用户没指定时就用这里。"""

    aspectRatio: str = "自动"  # 默认图片比例。
    resolution: str = "1K"  # 默认图片清晰度。
    maxConcurrentTasks: int = 3  # 同时最多跑几个生图任务。
    showGenerationInfo: bool = False  # 成功后是否显示耗时和数量。
    showModelInfo: bool = False  # 成功后是否显示模型名。


class ImageData:  # 定义一组放在一起的数据或行为。
    """
    插件数据入口。

    这个类把 AstrBot 原始配置变成人更容易读的对象。比如配置里叫 api_providers，
    这里会整理成 self.providers；配置里叫 user_limits，这里会整理成 self.userLimit。
    """

    def __init__(self, config: AstrBotConfig, dataDir: Path):  # 定义一个可重复调用的小动作。
        self.rawConfig = config  # AstrBot 给插件的原始配置对象，保存设置时还要写回它。
        self.dataDir = dataDir  # 插件数据目录，usage.json 会放在这里。
        self.usageFile = dataDir / "usage.json"  # 用户每日用量文件。
        self.providers: list[ProviderConfig] = []  # 所有可用供应商配置。
        self.currentProvider: ProviderConfig | None = None  # 当前正在使用的供应商。
        self.userLimit = UserLimit()  # 用户限速和每日次数设置。
        self.cacheLimit = CacheLimit()  # 图片缓存设置。
        self.imageDefault = ImageDefault()  # 默认比例、分辨率、并发数等。
        self.presets: dict[str, Any] = {}  # 预设名到提示词的映射。
        self.enableLLMTool = True  # 是否允许 LLM 自动调用生图工具。
        self.usageCountByDate: dict[str, dict[str, int]] = {}  # 格式：{"2026-04-26": {"用户ID": 3}}。
        self.lastRequestTimeByUser: dict[str, float] = {}  # 用户上次请求时间，用来限速。
        self.load()  # 先读取配置。
        self.loadUsage()  # 再读取每日用量。

    def load(self) -> None:  # 定义一个可重复调用的小动作。
        """从 AstrBot 配置读取全部设置；模型切换后也会重新读取。"""
        generation = self.rawConfig.get("generation", {})  # 生图设置原始字典。
        userLimits = self.rawConfig.get("user_limits", {})  # 用户限制原始字典。
        cache = self.rawConfig.get("cache", {})  # 缓存设置原始字典。
        self.enableLLMTool = self.rawConfig.get("enable_llm_tool", True)  # 没写配置时默认开启 LLM 工具。
        self.providers = self.readProviders(self.rawConfig.get("api_providers", []), generation)  # 读取所有供应商。
        self.currentProvider = self.findCurrentProvider(generation.get("model", ""))  # 按当前模型找到供应商。
        self.userLimit = UserLimit(  # 保存这一项数据，后面的流程会继续使用。
            rateLimitSeconds=max(0, userLimits.get("rate_limit_seconds", 0)),  # 小于 0 没意义，所以压到 0。
            enableDailyLimit=userLimits.get("enable_daily_limit", False),  # 保存这一项数据，后面的流程会继续使用。
            dailyLimitCount=max(1, userLimits.get("daily_limit_count", 10)),  # 每日次数至少为 1。
            maxImageSizeMB=max(1, userLimits.get("max_image_size_mb", 10)),  # 图片大小至少为 1MB。
        )  # 这一行按当前流程执行，作用见上方说明。
        self.cacheLimit = CacheLimit(  # 保存这一项数据，后面的流程会继续使用。
            maxCacheCount=max(1, cache.get("max_cache_count", 100)),  # 配置文件字段固定叫 max_cache_count，不能改。
            cleanupIntervalHours=max(1, cache.get("cleanup_interval_hours", 24)),  # 至少 1 小时清理一次。
        )  # 这一行按当前流程执行，作用见上方说明。
        self.imageDefault = ImageDefault(  # 保存这一项数据，后面的流程会继续使用。
            aspectRatio=generation.get("default_aspect_ratio", "自动"),  # 配置文件字段固定叫 default_aspect_ratio，不能改。
            resolution=generation.get("default_resolution", "1K"),  # 保存这一项数据，后面的流程会继续使用。
            maxConcurrentTasks=max(1, generation.get("max_concurrent_tasks", 3)),  # 保存这一项数据，后面的流程会继续使用。
            showGenerationInfo=generation.get("show_generation_info", False),  # 保存这一项数据，后面的流程会继续使用。
            showModelInfo=generation.get("show_model_info", False),  # 保存这一项数据，后面的流程会继续使用。
        )  # 这一行按当前流程执行，作用见上方说明。
        self.presets = self.readPresets(self.rawConfig.get("presets", []))  # 读取“名称:内容”格式的预设。

    def loadUsage(self) -> None:  # 定义一个可重复调用的小动作。
        """读取 usage.json；文件不存在就从空数据开始。"""
        if not self.usageFile.exists():  # 先判断这个情况，避免后面流程出错。
            self.usageCountByDate = {}  # 第一次运行还没有用量文件，这是正常情况。
            return  # 结束当前流程，不再继续往下走。

        try:  # 尝试执行可能失败的外部操作。
            self.usageCountByDate = json.loads(self.usageFile.read_text(encoding="utf-8"))  # 读取每日用量。
            self.removeOldUsage()  # 顺手清掉太久以前的数据。
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[ImageGen] 加载用量数据失败: {exc}")  # 这一行按当前流程执行，作用见上方说明。
            self.usageCountByDate = {}  # 文件坏了就丢弃，避免插件启动失败。

    def checkUserCanGenerate(self, userID: str) -> bool | str:  # 定义一个可重复调用的小动作。
        """检查用户能不能开始生图；能就返回 True，不能就返回原因。"""
        if self.userLimit.rateLimitSeconds > 0:  # 先判断这个情况，避免后面流程出错。
            now = time.time()  # 当前时间，单位是秒。
            lastTime = self.lastRequestTimeByUser.get(userID, 0)  # 这个用户上次请求时间。
            if now - lastTime < self.userLimit.rateLimitSeconds:  # 先判断这个情况，避免后面流程出错。
                remain = int(self.userLimit.rateLimitSeconds - (now - lastTime))  # 还要等几秒。
                return f"请求过于频繁，请在 {remain} 秒后再试。"  # 把结果交回调用者，这就是本步的反馈。
            self.lastRequestTimeByUser[userID] = now  # 通过检查后立刻记时间，防止同时连发。

        if self.userLimit.enableDailyLimit:  # 先判断这个情况，避免后面流程出错。
            today = self.today()  # 今天日期字符串。
            userCount = self.usageCountByDate.setdefault(today, {}).get(userID, 0)  # 今天已经成功几次。
            if userCount >= self.userLimit.dailyLimitCount:  # 先判断这个情况，避免后面流程出错。
                return f"你今天的生图额度已用完（{self.userLimit.dailyLimitCount} 次），请明天再试。"  # 把结果交回调用者，这就是本步的反馈。
        return True  # 把结果交回调用者，这就是本步的反馈。

    def recordUserUsage(self, userID: str) -> None:  # 定义一个可重复调用的小动作。
        """生成成功后给用户今日次数加 1。"""
        if not self.userLimit.enableDailyLimit:  # 先判断这个情况，避免后面流程出错。
            return  # 没开每日限制时不写 usage.json，减少无用文件写入。

        today = self.today()  # 今天日期。
        self.usageCountByDate.setdefault(today, {})  # 没有今天这一栏就先创建。
        self.usageCountByDate[today][userID] = self.usageCountByDate[today].get(userID, 0) + 1  # 次数加 1。
        self.saveUsage()  # 写回文件，重启后还能记得。

    def getUserUsageCount(self, userID: str) -> int:  # 定义一个可重复调用的小动作。
        """读取用户今天已经成功生成的次数。"""
        return self.usageCountByDate.get(self.today(), {}).get(userID, 0)  # 把结果交回调用者，这就是本步的反馈。

    def saveCurrentModel(self, model: str) -> None:  # 定义一个可重复调用的小动作。
        """保存当前模型；model 格式是“供应商名称/模型名称”。"""
        self.rawConfig.setdefault("generation", {})["model"] = model  # 写回 AstrBot 配置字典。
        self.rawConfig.save_config()  # 保存到配置文件。
        self.load()  # 重新读取，让 currentProvider 立刻更新。

    def savePreset(self, name: str, content: str) -> None:  # 定义一个可重复调用的小动作。
        """保存一个预设。"""
        self.presets[name] = content  # 先改内存数据。
        self.rawConfig["presets"] = [f"{key}:{value}" for key, value in self.presets.items()]  # 再改 AstrBot 配置格式。
        self.rawConfig.save_config()  # 写入配置文件。

    def deletePreset(self, name: str) -> bool:  # 定义一个可重复调用的小动作。
        """删除一个预设；删到了返回 True，没找到返回 False。"""
        if name not in self.presets:  # 先判断这个情况，避免后面流程出错。
            return False  # 把结果交回调用者，这就是本步的反馈。

        del self.presets[name]  # 删除内存数据。
        self.rawConfig["presets"] = [f"{key}:{value}" for key, value in self.presets.items()]  # 同步配置列表。
        self.rawConfig.save_config()  # 写入配置文件。
        return True  # 把结果交回调用者，这就是本步的反馈。

    def getProviderByType(self, providerType: ProviderType) -> ProviderConfig | None:  # 定义一个可重复调用的小动作。
        """按供应商种类找配置；Jimeng 每日领积分会用到。"""
        for provider in self.providers:  # 逐个处理这组内容，避免漏掉任何一项。
            if provider.type == providerType:  # 先判断这个情况，避免后面流程出错。
                return provider  # 把结果交回调用者，这就是本步的反馈。
        return None  # 把结果交回调用者，这就是本步的反馈。

    def getAvailableModels(self) -> list[str]:  # 定义一个可重复调用的小动作。
        """返回所有可切换模型，格式是“供应商名称/模型名称”。"""
        models: list[str] = []  # 保存这一项数据，后面的流程会继续使用。
        for provider in self.providers:  # 逐个处理这组内容，避免漏掉任何一项。
            for model in provider.availableModels:  # 逐个处理这组内容，避免漏掉任何一项。
                models.append(f"{provider.name}/{model}")  # 这一行按当前流程执行，作用见上方说明。
        return models  # 把结果交回调用者，这就是本步的反馈。

    def saveUsage(self) -> None:  # 定义一个可重复调用的小动作。
        """把每日用量写回 usage.json。"""
        try:  # 尝试执行可能失败的外部操作。
            self.dataDir.mkdir(parents=True, exist_ok=True)  # 确保目录存在。
            text = json.dumps(self.usageCountByDate, ensure_ascii=False, indent=2)  # 转成好读的 JSON。
            self.usageFile.write_text(text, encoding="utf-8")  # 写入文件。
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[ImageGen] 保存用量数据失败: {exc}")  # 这一行按当前流程执行，作用见上方说明。

    def today(self) -> str:  # 定义一个可重复调用的小动作。
        """返回今天日期，格式固定为 YYYY-MM-DD。"""
        return datetime.date.today().isoformat()  # 把结果交回调用者，这就是本步的反馈。

    def readProviders(self, rawProviders: list[Any], generation: dict[str, Any]) -> list[ProviderConfig]:  # 定义一个可重复调用的小动作。
        """把 AstrBot 的供应商配置列表整理成 ProviderConfig。"""
        providers: list[ProviderConfig] = []  # 保存这一项数据，后面的流程会继续使用。
        for item in rawProviders:  # 逐个处理这组内容，避免漏掉任何一项。
            if not isinstance(item, dict):  # 先判断这个情况，避免后面流程出错。
                continue  # 配置项不是字典就跳过，防止坏配置让插件崩掉。
            try:  # 尝试执行可能失败的外部操作。
                providerType = ProviderType(item.get("__template_key"))  # AstrBot 用这个字段表示供应商模板。
            except ValueError:  # 把异常变成可读的错误或日志，避免插件崩掉。
                logger.warning(f"[ImageGen] 忽略未知供应商类型: {item.get('__template_key')}")  # 这一行按当前流程执行，作用见上方说明。
                continue  # 这一行按当前流程执行，作用见上方说明。
            providers.append(
                ProviderConfig(  # 这一行按当前流程执行，作用见上方说明。
                    type=providerType,  # 保存这一项数据，后面的流程会继续使用。
                    name=item.get("name", ""),  # 保存这一项数据，后面的流程会继续使用。
                    baseURL=self.cleanBaseURL((item.get("base_url") or "").strip()),  # 保存这一项数据，后面的流程会继续使用。
                    apiKeys=[key for key in item.get("api_keys", []) if key],  # 保存这一项数据，后面的流程会继续使用。
                    availableModels=item.get("available_models") or [],  # 保存这一项数据，后面的流程会继续使用。
                    proxy=(item.get("proxy") or "").strip() or None,  # 保存这一项数据，后面的流程会继续使用。
                    timeout=generation.get("timeout", 180),  # 保存这一项数据，后面的流程会继续使用。
                    maxRetryTimes=generation.get("max_retry_attempts", 3),  # 保存这一项数据，后面的流程会继续使用。
                )
            )  # 这一行按当前流程执行，作用见上方说明。
        return providers  # 把结果交回调用者，这就是本步的反馈。

    def findCurrentProvider(self, modelText: str) -> ProviderConfig | None:  # 定义一个可重复调用的小动作。
        """按“供应商/模型”找到当前供应商；没写就用第一个可用供应商。"""
        provider = None  # 保存这一项数据，后面的流程会继续使用。
        model = ""  # 保存这一项数据，后面的流程会继续使用。
        if "/" in modelText:  # 先判断这个情况，避免后面流程出错。
            providerName, model = modelText.split("/", 1)  # 左边是供应商名，右边是模型名。
            provider = next((item for item in self.providers if item.name == providerName), None)  # 保存这一项数据，后面的流程会继续使用。
        if not provider and self.providers:  # 先判断这个情况，避免后面流程出错。
            provider = self.providers[0]  # 没匹配到就用第一个供应商。
            model = provider.availableModels[0] if provider.availableModels else ""  # 供应商有模型列表就用第一个。
            logger.info(f"[ImageGen] 未匹配到当前模型配置，默认使用: {provider.name}/{model}")  # 这一行按当前流程执行，作用见上方说明。
        if provider:  # 先判断这个情况，避免后面流程出错。
            provider.model = model  # 把当前模型写到供应商对象上。
        else:  # 前面情况都不符合时，走这个备用分支。
            logger.error("[ImageGen] 未找到任何有效的生图模型配置")  # 这一行按当前流程执行，作用见上方说明。
        return provider  # 把结果交回调用者，这就是本步的反馈。

    def readPresets(self, rawPresets: list[Any]) -> dict[str, Any]:  # 定义一个可重复调用的小动作。
        """把“名称:内容”格式的预设列表转成字典。"""
        presets: dict[str, Any] = {}  # 保存这一项数据，后面的流程会继续使用。
        if not isinstance(rawPresets, list):  # 先判断这个情况，避免后面流程出错。
            return presets  # 把结果交回调用者，这就是本步的反馈。
        for item in rawPresets:  # 逐个处理这组内容，避免漏掉任何一项。
            if isinstance(item, str) and ":" in item:  # 先判断这个情况，避免后面流程出错。
                name, prompt = item.split(":", 1)  # 只切第一个冒号，避免 JSON 里的冒号被切坏。
                if name.strip() and prompt.strip():  # 先判断这个情况，避免后面流程出错。
                    presets[name.strip()] = prompt.strip()  # 保存这一项数据，后面的流程会继续使用。
        return presets  # 把结果交回调用者，这就是本步的反馈。

    def removeOldUsage(self) -> None:  # 定义一个可重复调用的小动作。
        """只保留最近 7 天的用量数据。"""
        today = datetime.date.today()  # 保存这一项数据，后面的流程会继续使用。
        oldDays: list[str] = []  # 保存这一项数据，后面的流程会继续使用。
        for day in self.usageCountByDate:  # 逐个处理这组内容，避免漏掉任何一项。
            try:  # 尝试执行可能失败的外部操作。
                if (today - datetime.date.fromisoformat(day)).days > 7:  # 先判断这个情况，避免后面流程出错。
                    oldDays.append(day)  # 这一行按当前流程执行，作用见上方说明。
            except ValueError:  # 把异常变成可读的错误或日志，避免插件崩掉。
                oldDays.append(day)  # 日期格式坏了也删掉。
        for day in oldDays:  # 逐个处理这组内容，避免漏掉任何一项。
            del self.usageCountByDate[day]  # 这一行按当前流程执行，作用见上方说明。
        if oldDays:  # 先判断这个情况，避免后面流程出错。
            self.saveUsage()  # 这一行按当前流程执行，作用见上方说明。

    def cleanBaseURL(self, url: str) -> str:  # 定义一个可重复调用的小动作。
        """清理用户填写的网址；供应商文件会自己补 /v1。"""
        if not url:  # 先判断这个情况，避免后面流程出错。
            return ""  # 把结果交回调用者，这就是本步的反馈。
        url = url.rstrip("/")  # 去掉末尾斜杠，避免后面拼地址变成双斜杠。
        if "/v1" in url:  # 先判断这个情况，避免后面流程出错。
            url = url.split("/v1", 1)[0]  # 用户填了 /v1 时先去掉，后面统一补。
        return url.rstrip("/")  # 把结果交回调用者，这就是本步的反馈。
