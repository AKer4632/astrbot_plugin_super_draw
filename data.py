"""
插件的数据层：配置读取、用户用量、预设管理、生图模型切换。

从 AstrBot 配置读取多个生图供应商，每个供应商可以配置多个模型。
这个文件只保存和整理数据，不直接生图、不发消息；main.py 负责接收指令，generate.py 负责调用接口。

调用示例：
data = PluginData(config, dataDir)
reason = data.checkUser("user_123")
data.recordUsage("user_123")
prompt, presetName = data.resolvePreset("手办化 加个透明盒子")
data.addPreset("手办化", "高质量手办照片")
size = PluginData.mapAspectRatio("16:9")
modelListText = data.formatModelList()
switchText = data.switchModel(1)
"""

from __future__ import annotations

import datetime
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig


@dataclass
class ImageProvider:
    """
    一个生图供应商的配置。
    name 是给人看的供应商名，apiType 决定走 OpenAI 兼容接口还是 Gemini 官方接口。
    baseURL 只给 OpenAI 兼容接口使用，Gemini 官方接口会自动忽略它。
    """

    name: str
    apiType: str
    baseURL: str
    apiKeys: list[str]
    availableModels: list[str]


class PluginData:
    """
    插件数据入口。
    把 AstrBot 原始配置变成清晰的属性，管理用量、预设、当前生图供应商和当前模型。
    """

    def __init__(self, config: AstrBotConfig, dataDir: Path):
        self.rawConfig = config  # AstrBot 原始配置对象
        self.dataDir = dataDir  # 插件数据目录
        self.usageFile = dataDir / "usage.json"  # 用户每日用量文件

        # ─── API 供应商配置 ───
        self.providers: list[ImageProvider] = []  # 所有可用供应商
        self.availableModels: list[dict[str, str]] = []  # 展平后的模型列表，方便 /生图模型 按数字切换
        self.currentModelKey: str = ""  # 当前模型完整名，格式：供应商/模型
        self.currentProvider: ImageProvider | None = None  # 当前使用的供应商
        self.apiKeys: list[str] = []  # 当前供应商 API Key 列表
        self.apiType: str = "openai"  # 当前供应商接口类型：openai 或 gemini
        self.baseURL: str = ""  # 当前供应商 API 基础地址
        self.model: str = "gpt-image-2"  # 当前模型名
        self.timeout: int = 180  # 请求超时秒数（固定值，不展示配置）
        self.maxRetry: int = 3  # 最大重试次数
        self.maxConcurrent: int = 3  # 最大并发任务数

        # ─── 生图默认值 ───
        self.defaultQuality: str = "medium"  # OpenAI quality 值（low/medium/high）

        # ─── 用户限制 ───
        self.rateLimitSeconds: int = 0  # 两次请求最小间隔秒数
        self.enableDailyLimit: bool = False  # 是否开启每日次数限制
        self.dailyLimitCount: int = 10  # 每人每天最多生成次数

        # ─── 缓存配置（固定值，不展示配置）───
        self.maxCacheCount: int = 100  # 缓存最多保留文件数
        self.cleanupIntervalHours: int = 24  # 清理间隔小时数

        # ─── LLM 工具 ───
        self.enabled: bool = True  # 总开关
        self.enableLLMTool: bool = True  # 是否注册 LLM 工具

        # ─── 预设 ───
        self.presets: dict[str, str] = {}  # 预设名 -> 提示词

        # ─── 运行时数据 ───
        self.usageCountByDate: dict[str, dict[str, int]] = {}  # {"2026-05-19": {"用户ID": 3}}
        self.lastRequestTimeByUser: dict[str, float] = {}  # 用户上次请求时间戳

        self._loadConfig()
        self._loadUsage()

    # ═══════════════════════════════════════════════════════════════════════════
    # 用户限制
    # ═══════════════════════════════════════════════════════════════════════════

    def checkUser(self, userID: str) -> str | None:
        """检查用户能否生图；能返回 None，不能返回原因字符串。"""
        if self.rateLimitSeconds > 0:
            now = time.time()  # 当前时间用来计算冷却间隔
            lastTime = self.lastRequestTimeByUser.get(userID, 0)  # 没记录过就按 0 处理，第一次一定能通过
            if now - lastTime < self.rateLimitSeconds:
                remain = int(self.rateLimitSeconds - (now - lastTime))  # 向下取整即可，提示不用精确到毫秒
                return f"请求过于频繁，请在 {remain} 秒后再试。"
            self.lastRequestTimeByUser[userID] = now  # 通过冷却检查后立刻记时间，避免用户连续开很多后台任务

        if self.enableDailyLimit:
            today = datetime.date.today().isoformat()  # 每天一个桶，只统计当天成功生成的次数
            userCount = self.usageCountByDate.setdefault(today, {}).get(userID, 0)  # 没生成过就是 0 次
            if userCount >= self.dailyLimitCount:
                return f"你今天的生图额度已用完（{self.dailyLimitCount} 次），请明天再试。"

        return None

    def recordUsage(self, userID: str) -> None:
        """记录用户成功生图一次；只有开启每日限制时才需要落盘。"""
        if not self.enableDailyLimit:
            return

        today = datetime.date.today().isoformat()  # 用日期字符串做第一层 key，方便清理旧数据
        self.usageCountByDate.setdefault(today, {})  # 当天第一次记录时先创建当天账本
        self.usageCountByDate[today][userID] = self.usageCountByDate[today].get(userID, 0) + 1  # 成功一次才加一次
        self._saveUsage()  # 写回 usage.json，重启插件后额度仍然准确

    def getUserUsageCount(self, userID: str) -> int:
        """读取用户今天已经成功生成的次数。"""
        today = datetime.date.today().isoformat()
        return self.usageCountByDate.get(today, {}).get(userID, 0)

    # ═══════════════════════════════════════════════════════════════════════════
    # 生图模型切换
    # ═══════════════════════════════════════════════════════════════════════════

    def formatModelList(self) -> str:
        """返回可用生图模型列表；/生图模型 不带数字时直接发给用户。"""
        if not self.availableModels:
            return "当前没有可用生图模型，请先在插件配置里添加供应商、API Key 和模型。"

        lines = ["可用生图模型："]  # 文本第一行先说明这是列表，用户不用猜数字含义
        for index, item in enumerate(self.availableModels, 1):
            marker = " ✅" if item["key"] == self.currentModelKey else ""  # 当前模型加对勾，反馈更直观
            lines.append(f"{index}. {item['key']}{marker}")
        lines.append("\n发送 /生图模型 数字 可切换供应商和模型，例如：/生图模型 1")
        return "\n".join(lines)

    def formatPresetList(self) -> str:
        """把预设按编号列出来，方便用户查看每个预设的名字和简短说明。"""
        if not self.presets:
            return "当前没有预设。"

        lines = ["预设列表："]
        for index, (name, prompt) in enumerate(self.presets.items(), 1):
            shortPrompt = prompt[:20] + "..." if len(prompt) > 20 else prompt
            lines.append(f"{index}. {name}: {shortPrompt}")
        lines.append("\n发送 /预设 查看 名称 可查看完整内容，例如：/预设 查看 手办化")
        return "\n".join(lines)

    def getPresetDetail(self, name: str) -> str:
        """按名称查看一个预设的完整内容。"""
        presetName = name.strip()
        if not presetName:
            return "请提供要查看的预设名称。"

        matchedName = self._findPreset(presetName)
        if not matchedName:
            return f"预设不存在：{presetName}"

        return f"预设：{matchedName}\n\n{self.presets[matchedName]}"

    def switchModel(self, index: int) -> str:
        """按列表数字切换当前供应商和模型，同时写回 AstrBot 配置。"""
        if index < 1 or index > len(self.availableModels):
            return f"模型编号不存在，请发送 /生图模型 查看 1 到 {len(self.availableModels)} 的可选模型。"

        item = self.availableModels[index - 1]
        self._applyModelKey(item["key"])

        generation = self.rawConfig.get("generation", {})
        generation["model"] = self.currentModelKey
        self.rawConfig["generation"] = generation
        self.rawConfig.save_config()

        return f"已切换生图模型：{self.currentModelKey}"

    # ═══════════════════════════════════════════════════════════════════════════
    # 预设管理
    # ═══════════════════════════════════════════════════════════════════════════

    def resolvePreset(self, text: str) -> tuple[str, str | None]:
        """
        尝试把文本开头的预设名展开。
        返回 (最终prompt, 命中的预设名或None)。
        如果第一个词是预设名，就把预设内容替换进去，后面的文字追加到末尾。
        """
        if not text:
            return ("", None)

        # 把第一个词当作可能的预设名
        parts = text.split(maxsplit=1)
        firstWord = parts[0]
        extraText = parts[1] if len(parts) > 1 else ""

        # 查找预设：先精确匹配，再大小写不敏感匹配
        matchedName = self._findPreset(firstWord)
        if not matchedName:
            return (text, None)  # 没命中预设，原样返回

        # 命中预设，展开内容
        presetContent = self._readPresetContent(self.presets[matchedName])
        finalPrompt = f"{presetContent} {extraText}".strip() if extraText else presetContent
        return (finalPrompt, matchedName)

    def addPreset(self, name: str, content: str) -> None:
        """保存一个预设，同时写回 AstrBot 配置。"""
        self.presets[name] = content
        self.rawConfig["presets"] = [f"{k}:{v}" for k, v in self.presets.items()]
        self.rawConfig.save_config()

    def removePreset(self, name: str) -> bool:
        """删除一个预设；删到了返回 True，没找到返回 False。"""
        if name not in self.presets:
            return False
        del self.presets[name]
        self.rawConfig["presets"] = [f"{k}:{v}" for k, v in self.presets.items()]
        self.rawConfig.save_config()
        return True

    # ═══════════════════════════════════════════════════════════════════════════
    # 尺寸映射（静态方法，供 main.py、LLM 工具和 test.py 调用）
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def mapAspectRatio(ratio: str) -> str:
        """
        把 "1:1"、"16:9" 等宽高比映射成 OpenAI size 参数。
        横向比例映射到 1536x1024，纵向比例映射到 1024x1536。
        """
        sizeMap = {
            "auto": "auto",
            "自动": "auto",
            "1:1": "1024x1024",
            "3:2": "1536x1024",  # 横向
            "16:9": "1536x1024",  # 横向
            "4:3": "1536x1024",  # 横向
            "5:4": "1536x1024",  # 横向
            "21:9": "1536x1024",  # 超宽也归横向
            "2:3": "1024x1536",  # 纵向
            "9:16": "1024x1536",  # 纵向
            "3:4": "1024x1536",  # 纵向
            "4:5": "1024x1536",  # 纵向
            "1024x1024": "1024x1024",
            "1536x1024": "1536x1024",
            "1024x1536": "1024x1536",
        }
        return sizeMap.get(ratio, "auto")

    # ═══════════════════════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════════════════════

    def _loadConfig(self) -> None:
        """从 AstrBot 配置读取全部设置。"""
        self.providers = self._parseProviders(self.rawConfig.get("api_providers", []))
        if not self.providers:
            self.providers = self._parseOldSingleProvider(self.rawConfig.get("api", {}))
        self.availableModels = self._buildAvailableModels()

        # 生图配置
        gen = self.rawConfig.get("generation", {})
        self.maxRetry = gen.get("max_retry_attempts", 3)
        self.maxConcurrent = max(1, gen.get("max_concurrent_tasks", 3))
        self.defaultQuality = gen.get("default_quality", "medium")
        self._applyModelKey(gen.get("model", ""))

        # 用户限制
        limits = self.rawConfig.get("user_limits", {})
        self.rateLimitSeconds = max(0, limits.get("rate_limit_seconds", 0))
        self.enableDailyLimit = limits.get("enable_daily_limit", False)
        self.dailyLimitCount = max(1, limits.get("daily_limit_count", 10))

        # LLM 工具
        self.enabled = self.rawConfig.get("enabled", True)
        self.enableLLMTool = self.rawConfig.get("enable_llm_tool", True)

        # 预设
        self.presets = self._parsePresets(self.rawConfig.get("presets", []))

    def _parseProviders(self, rawProviders: Any) -> list[ImageProvider]:
        """把 template_list 的供应商配置整理成 ImageProvider 列表。"""
        providers: list[ImageProvider] = []
        if not isinstance(rawProviders, list):
            return providers

        for index, rawProvider in enumerate(rawProviders, 1):
            if not isinstance(rawProvider, dict):
                continue

            name = str(rawProvider.get("name") or f"供应商{index}").strip()  # 没填名称就用顺序生成一个可读名字
            apiType = self._cleanApiType(str(rawProvider.get("api_type") or "openai"))  # 写错也收束成固定接口类型
            baseURL = self._cleanBaseURL(str(rawProvider.get("base_url") or ""))  # OpenAI 中转地址去掉多余 /v1
            apiKeys = [key for key in rawProvider.get("api_keys", []) if key]  # 空 Key 直接丢掉，避免请求时报奇怪错误
            models = [str(model).strip() for model in rawProvider.get("available_models", []) if str(model).strip()]  # 空模型不展示

            if apiKeys and models:
                providers.append(ImageProvider(name=name, apiType=apiType, baseURL=baseURL, apiKeys=apiKeys, availableModels=models))
        return providers

    def _parseOldSingleProvider(self, api: Any) -> list[ImageProvider]:
        """兼容旧版 api 单供应商配置，避免老用户升级后立刻不可用。"""
        if not isinstance(api, dict):
            return []

        apiKeys = [key for key in api.get("api_keys", []) if key]
        model = api.get("model", "gpt-image-2") or "gpt-image-2"
        if not apiKeys:
            return []

        return [
            ImageProvider(
                name="OpenAI",
                apiType="openai",
                baseURL=self._cleanBaseURL((api.get("base_url") or "").strip()),
                apiKeys=apiKeys,
                availableModels=[model],
            )
        ]

    def _buildAvailableModels(self) -> list[dict[str, str]]:
        """把多个供应商的多个模型展平成一个列表，方便用数字选择。"""
        result: list[dict[str, str]] = []
        for provider in self.providers:
            for model in provider.availableModels:
                result.append({"key": f"{provider.name}/{model}", "provider": provider.name, "model": model})
        return result

    def _applyModelKey(self, modelKey: str) -> None:
        """根据 '供应商/模型' 设置当前供应商和当前模型；空值或无效值时使用第一个可用模型。"""
        target = modelKey or (self.availableModels[0]["key"] if self.availableModels else "")
        matched = next((item for item in self.availableModels if item["key"] == target), None)
        if not matched and self.availableModels:
            matched = self.availableModels[0]

        if not matched:
            self.currentModelKey = ""
            self.currentProvider = None
            self.apiKeys = []
            self.apiType = "openai"
            self.baseURL = ""
            self.model = "gpt-image-2"
            return

        provider = next((item for item in self.providers if item.name == matched["provider"]), None)
        if not provider:
            return

        self.currentModelKey = matched["key"]
        self.currentProvider = provider
        self.apiType = provider.apiType
        self.apiKeys = provider.apiKeys
        self.baseURL = provider.baseURL
        self.model = matched["model"]

    def _loadUsage(self) -> None:
        """读取 usage.json；文件不存在就从空数据开始。"""
        if not self.usageFile.exists():
            self.usageCountByDate = {}
            return
        try:
            self.usageCountByDate = json.loads(self.usageFile.read_text(encoding="utf-8"))
            self._removeOldUsage()
        except Exception as exc:
            logger.error(f"[SuperDraw] 加载用量数据失败: {exc}")
            self.usageCountByDate = {}

    def _saveUsage(self) -> None:
        """把每日用量写回 usage.json。"""
        try:
            self.dataDir.mkdir(parents=True, exist_ok=True)
            text = json.dumps(self.usageCountByDate, ensure_ascii=False, indent=2)
            self.usageFile.write_text(text, encoding="utf-8")
        except Exception as exc:
            logger.error(f"[SuperDraw] 保存用量数据失败: {exc}")

    def _removeOldUsage(self) -> None:
        """只保留最近 7 天的用量数据，避免文件无限增长。"""
        today = datetime.date.today()
        oldDays = [day for day in self.usageCountByDate if self._isOldDate(day, today)]
        for day in oldDays:
            del self.usageCountByDate[day]
        if oldDays:
            self._saveUsage()

    def _isOldDate(self, dateStr: str, today: datetime.date) -> bool:
        """判断日期是否超过 7 天。"""
        try:
            return (today - datetime.date.fromisoformat(dateStr)).days > 7
        except ValueError:
            return True  # 格式不对的也删掉

    def _findPreset(self, token: str) -> str | None:
        """查找预设名；先精确匹配，再大小写不敏感匹配。"""
        if token in self.presets:
            return token
        for name in self.presets:
            if name.lower() == token.lower():
                return name
        return None

    def _readPresetContent(self, content: str) -> str:
        """
        读取预设内容。
        支持两种格式：纯文本直接返回，JSON 格式提取 prompt 字段。
        """
        if not content.strip().startswith("{"):
            return content

        # 尝试解析 JSON 格式预设
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "prompt" in data:
                return data["prompt"]
        except json.JSONDecodeError:
            pass
        return content  # 解析失败就当纯文本

    @staticmethod
    def _parsePresets(rawPresets: list[Any]) -> dict[str, str]:
        """把 "名称:内容" 格式的预设列表转成字典。"""
        presets: dict[str, str] = {}
        if not isinstance(rawPresets, list):
            return presets
        for item in rawPresets:
            if isinstance(item, str) and ":" in item:
                name, prompt = item.split(":", 1)
                if name.strip() and prompt.strip():
                    presets[name.strip()] = prompt.strip()
        return presets

    @staticmethod
    def _cleanApiType(apiType: str) -> str:
        """把配置里的接口类型整理成固定值；写错时默认用 OpenAI 兼容接口。"""
        text = (apiType or "openai").strip().lower()
        return "gemini" if text == "gemini" else "openai"

    @staticmethod
    def _cleanBaseURL(url: str) -> str:
        """清理用户填写的网址；去掉末尾斜杠和 /v1。"""
        if not url:
            return ""
        url = url.rstrip("/")
        if "/v1" in url:
            url = url.split("/v1", 1)[0]
        return url.rstrip("/")
