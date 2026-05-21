"""
插件的数据层：配置读取、用户用量、预设管理。

从 AstrBot 配置读取 API 设置和生图参数，管理用户每日用量和预设提示词。
它只做数据存取，不做生图业务逻辑，也不发消息。

调用示例：
data = PluginData(config, dataDir)
reason = data.checkUser("user_123")
data.recordUsage("user_123")
prompt, presetName = data.resolvePreset("手办化 加个透明盒子")
data.addPreset("手办化", "高质量手办照片")
size = PluginData.mapAspectRatio("16:9")
"""

from __future__ import annotations

import datetime
import json
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig


class PluginData:
    """
    插件数据入口。
    把 AstrBot 原始配置变成清晰的属性，管理用量和预设的读写。
    """

    def __init__(self, config: AstrBotConfig, dataDir: Path):
        self.rawConfig = config  # AstrBot 原始配置对象
        self.dataDir = dataDir  # 插件数据目录
        self.usageFile = dataDir / "usage.json"  # 用户每日用量文件

        # ─── API 配置 ───
        self.apiKeys: list[str] = []  # API Key 列表
        self.baseURL: str = ""  # API 基础地址
        self.model: str = "gpt-image-2"  # 模型名
        self.timeout: int = 180  # 请求超时秒数（保留但不展示配置）
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

        # 频率限制：两次请求间隔不够
        if self.rateLimitSeconds > 0:
            now = time.time()
            lastTime = self.lastRequestTimeByUser.get(userID, 0)
            if now - lastTime < self.rateLimitSeconds:
                remain = int(self.rateLimitSeconds - (now - lastTime))
                return f"请求过于频繁，请在 {remain} 秒后再试。"
            self.lastRequestTimeByUser[userID] = now

        # 每日次数限制
        if self.enableDailyLimit:
            today = datetime.date.today().isoformat()
            userCount = self.usageCountByDate.setdefault(today, {}).get(userID, 0)
            if userCount >= self.dailyLimitCount:
                return f"你今天的生图额度已用完（{self.dailyLimitCount} 次），请明天再试。"

        return None

    def recordUsage(self, userID: str) -> None:
        """记录用户成功生图一次。"""
        if not self.enableDailyLimit:
            return
        today = datetime.date.today().isoformat()
        self.usageCountByDate.setdefault(today, {})
        self.usageCountByDate[today][userID] = self.usageCountByDate[today].get(userID, 0) + 1
        self._saveUsage()

    def getUserUsageCount(self, userID: str) -> int:
        """读取用户今天已经成功生成的次数。"""
        today = datetime.date.today().isoformat()
        return self.usageCountByDate.get(today, {}).get(userID, 0)

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
    # 尺寸/质量映射（静态方法，供 main.py 和 LLM 工具调用）
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def mapAspectRatio(ratio: str) -> str:
        """
        把 "1:1"、"16:9" 等宽高比映射成 OpenAI size 参数。
        横向比例映射到 1536x1024，纵向比例映射到 1024x1536。
        """
        sizeMap = {
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
        }
        return sizeMap.get(ratio, "auto")

    # ═══════════════════════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════════════════════

    def _loadConfig(self) -> None:
        """从 AstrBot 配置读取全部设置。"""
        # API 配置
        api = self.rawConfig.get("api", {})
        self.apiKeys = [k for k in api.get("api_keys", []) if k]
        self.baseURL = self._cleanBaseURL((api.get("base_url") or "").strip())
        self.model = api.get("model", "gpt-image-2") or "gpt-image-2"

        # 生图配置
        gen = self.rawConfig.get("generation", {})
        self.maxRetry = gen.get("max_retry_attempts", 3)
        self.maxConcurrent = max(1, gen.get("max_concurrent_tasks", 3))

        # 默认质量（直接使用配置值，不再做映射）
        self.defaultQuality = gen.get("default_quality", "medium")

        # 用户限制
        limits = self.rawConfig.get("user_limits", {})
        self.rateLimitSeconds = max(0, limits.get("rate_limit_seconds", 0))
        self.enableDailyLimit = limits.get("enable_daily_limit", False)
        self.dailyLimitCount = max(1, limits.get("daily_limit_count", 10))

        # LLM 工具
        self.enableLLMTool = self.rawConfig.get("enable_llm_tool", True)

        # 预设
        self.presets = self._parsePresets(self.rawConfig.get("presets", []))

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
    def _cleanBaseURL(url: str) -> str:
        """清理用户填写的网址；去掉末尾斜杠和 /v1。"""
        if not url:
            return ""
        url = url.rstrip("/")
        if "/v1" in url:
            url = url.split("/v1", 1)[0]
        return url.rstrip("/")
