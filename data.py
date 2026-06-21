"""
插件数据层：配置、用量、预设。

读取 AstrBot 的插件配置，把它整理成代码能直接用的字段。
同时管理用户的生图次数、冷却时间和提示词预设。

这个文件不调用任何生图接口，也不发消息，只负责"数据"这一件事。
generate.py 需要的 provider 列表就从这里拿，main.py 需要的用户限制也从这里查。

provider 格式（普通 dict，直接传给 generate.makeImages）：
    {"name": "OpenAI", "apiType": "openai", "baseUrl": "https://api.openai.com",
     "apiKeys": ["sk-xxx"], "model": "gpt-image-2", "timeout": 180, "maxRetry": 3}

调用示例：
    data = PluginData(config, dataDir)
    data.providers                          # -> 所有可用的 provider 列表
    data.checkUser("user123")               # -> None 表示可以生图，返回字符串表示被限制
    data.recordUsage("user123")             # -> 生图成功后记一次
    data.resolvePreset("手办化 一只猫")      # -> ("Your task is... 一只猫", "手办化")
"""

from __future__ import annotations

import datetime  # 日期计算，用于每日用量统计
import json  # 读写用量文件
import time  # 冷却时间判断
from pathlib import Path
from typing import Any

from astrbot.api import logger  # AstrBot 日志
from astrbot.core.config.astrbot_config import AstrBotConfig  # AstrBot 配置对象


class PluginData:
    """插件配置和数据的集中存储。初始化时自动读取配置和历史用量。"""

    def __init__(self, config: AstrBotConfig, dataDir: Path):
        self.rawConfig = config  # 原始配置对象，切换模型时需要写回
        self.dataDir = dataDir  # 插件数据目录
        self.usageFile = dataDir / "usage.json"  # 用量记录文件

        # ---- 生图配置 ----
        self.providers: list[dict] = []  # 所有可用的 provider（每个模型一条记录）
        self.models: list[dict[str, str]] = []  # 模型列表，用于 /生图模型 展示和切换
        self.currentModelKey: str = ""  # 当前选中的模型，格式："供应商名/模型名"
        self.currentProviderIdx: int = 0  # 当前模型在 providers 列表里的下标
        self.maxConcurrent: int = 3  # 最大并发生图任务数
        self.defaultQuality: str = "medium"  # 默认图片质量
        self.defaultSize: str = "auto"  # 默认图片比例
        self.saveFormat: str = "png"  # 图片保存格式

        # ---- 用户限制 ----
        self.rateLimitSeconds: int = 0  # 两次生图的最小间隔（秒），0 不限制
        self.enableDailyLimit: bool = False  # 是否启用每日次数限制
        self.dailyLimitCount: int = 10  # 每日最多生图次数

        # ---- 缓存管理 ----
        self.maxCacheCount: int = 100  # 缓存目录最多保留多少个文件
        self.cleanupIntervalHours: int = 24  # 清理缓存的间隔（小时）

        # ---- 开关 ----
        self.enabled: bool = True  # 插件总开关
        self.enableLLMTool: bool = True  # 是否允许 LLM 工具调用

        # ---- 预设 ----
        self.presets: dict[str, str] = {}  # 预设名 -> 预设内容

        # ---- 运行时状态 ----
        self.usageByDate: dict[str, dict[str, int]] = {}  # 每日用量：{"2025-01-01": {"user123": 3}}
        self.lastReqTime: dict[str, float] = {}  # 每个用户的上次请求时间

        self._loadConfig()
        self._loadUsage()

    # ========== 读取配置 ==========

    def _loadConfig(self) -> None:
        """从 AstrBot 配置里读取所有字段，整理成代码能直接用的格式。"""

        # 解析 provider 列表
        self.providers = self._parseProviders(self.rawConfig.get("api_providers", []))

        # 整理模型列表：每个 provider 就是一个"供应商名/模型名"
        self.models = [{"key": f"{p['name']}/{p['model']}", "provider": p["name"], "model": p["model"]} for p in self.providers]

        # 生图行为配置
        gen = self.rawConfig.get("generation", {})
        self.maxConcurrent = max(1, gen.get("max_concurrent_tasks", 3))
        self.defaultQuality = gen.get("default_quality", "medium")
        self.defaultSize = gen.get("default_size", "auto")
        self.saveFormat = gen.get("save_format", "png")
        self._applyModel(gen.get("model", ""))  # 选中当前模型

        # 用户限制配置
        limits = self.rawConfig.get("user_limits", {})
        self.rateLimitSeconds = max(0, limits.get("rate_limit_seconds", 0))
        self.enableDailyLimit = limits.get("enable_daily_limit", False)
        self.dailyLimitCount = max(1, limits.get("daily_limit_count", 10))

        # 开关
        self.enabled = self.rawConfig.get("enabled", True)
        self.enableLLMTool = self.rawConfig.get("enable_llm_tool", True)

        # 预设：配置里是 ["名称:内容", ...] 格式
        for p in self.rawConfig.get("presets", []):
            if ":" in p:
                k, v = p.split(":", 1)
                self.presets[k.strip()] = v.strip()

    def _parseProviders(self, raw: Any) -> list[dict]:
        """
        把配置里的 api_providers 列表整理成 generate.py 能直接用的 provider dict 列表。
        每个供应商的每个模型会变成一条独立记录，方便逐个尝试。
        """

        result = []

        for i, rp in enumerate(raw if isinstance(raw, list) else []):
            if not isinstance(rp, dict):
                continue

            name = str(rp.get("name") or f"P{i + 1}").strip()
            apiType = "gemini" if str(rp.get("api_type", "")).lower() == "gemini" else "openai"
            baseUrl = str(rp.get("base_url") or "").rstrip("/")
            if "/v1" in baseUrl:  # 用户可能多写了 /v1，帮他去掉
                baseUrl = baseUrl.split("/v1", 1)[0].rstrip("/")
            if not baseUrl:
                baseUrl = "https://api.openai.com"  # OpenAI 默认地址

            keys = [k for k in rp.get("api_keys", []) if k]  # 过滤空 key
            models = [str(m).strip() for m in rp.get("available_models", []) if str(m).strip()]
            maxRetry = max(1, self.rawConfig.get("generation", {}).get("max_retry_attempts", 3))
            timeout = 180

            # 每个模型生成一条独立的 provider 记录
            for model in models:
                if keys:  # 没有 key 的 provider 跳过
                    result.append(
                        {
                            "name": name,
                            "apiType": apiType,
                            "baseUrl": baseUrl,
                            "apiKeys": keys,
                            "model": model,
                            "timeout": timeout,
                            "maxRetry": maxRetry,
                        }
                    )

        return result

    def _applyModel(self, key: str) -> None:
        """选中一个模型，更新 currentModelKey 和 currentProviderIdx。"""

        # 没指定就用第一个
        target = key or (self.models[0]["key"] if self.models else "")

        # 找到匹配的模型记录
        matched = next((m for m in self.models if m["key"] == target), self.models[0] if self.models else None)

        if not matched:
            self.currentModelKey = ""
            self.currentProviderIdx = 0
            return

        self.currentModelKey = matched["key"]

        # 找到这个模型在 providers 里的下标
        for i, p in enumerate(self.providers):
            if p["name"] == matched["provider"] and p["model"] == matched["model"]:
                self.currentProviderIdx = i
                break

    # ========== 用户限制 ==========

    def checkUser(self, userID: str) -> str | None:
        """
        检查用户能不能生图。
        能生图返回 None，不能生图返回原因字符串。
        """

        now = time.time()

        # 检查冷却时间
        if self.rateLimitSeconds > 0:
            elapsed = now - self.lastReqTime.get(userID, 0)
            if elapsed < self.rateLimitSeconds:
                remaining = int(self.rateLimitSeconds - elapsed)
                return f"请等待 {remaining} 秒。"
            self.lastReqTime[userID] = now  # 通过了就更新时间

        # 检查每日次数
        if self.enableDailyLimit:
            today = datetime.date.today().isoformat()
            used = self.usageByDate.setdefault(today, {}).get(userID, 0)
            if used >= self.dailyLimitCount:
                return f"今日生图已达上限（{self.dailyLimitCount}次）。"

        return None

    def recordUsage(self, userID: str) -> None:
        """生图成功后记录一次用量，写入磁盘。"""

        if not self.enableDailyLimit:
            return

        today = datetime.date.today().isoformat()
        todayUsage = self.usageByDate.setdefault(today, {})
        todayUsage[userID] = todayUsage.get(userID, 0) + 1

        try:
            self.dataDir.mkdir(parents=True, exist_ok=True)
            self.usageFile.write_text(json.dumps(self.usageByDate, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"[SuperDraw] 保存用量失败: {e}")

    def _loadUsage(self) -> None:
        """启动时加载历史用量，自动清理超过 7 天的旧记录。"""

        if not self.usageFile.exists():
            return

        try:
            self.usageByDate = json.loads(self.usageFile.read_text("utf-8"))
            today = datetime.date.today()
            oldKeys = [k for k in self.usageByDate if (today - datetime.date.fromisoformat(k)).days > 7]
            for k in oldKeys:
                del self.usageByDate[k]
        except Exception:
            self.usageByDate = {}

    # ========== 预设 ==========

    def resolvePreset(self, text: str) -> tuple[str, str | None]:
        """
        检查文本开头是否命中预设名。
        命中返回 (拼接后的提示词, 预设名)，没命中返回 (原文, None)。
        例如："手办化 一只猫" -> ("Your task is... 一只猫", "手办化")
        """

        if not text:
            return "", None

        parts = text.split(maxsplit=1)
        name = next((k for k in self.presets if k.lower() == parts[0].lower()), None)

        if not name:
            return text, None  # 没命中预设，原样返回

        content = self.presets[name]

        # 预设内容可能是 JSON 格式 {"prompt": "..."}，兼容处理
        if content.startswith("{"):
            try:
                content = json.loads(content).get("prompt", content)
            except Exception:
                pass

        extra = parts[1] if len(parts) > 1 else ""  # 预设名后面的自由文本
        return f"{content} {extra}".strip(), name

    def formatPresetList(self) -> str:
        """格式化预设列表，给用户看。"""

        if not self.presets:
            return "暂无预设。使用 /预设 添加 名称:内容 来创建。"

        lines = ["可用预设："]
        for name in self.presets:
            lines.append(f"  · {name}")
        lines.append("\n使用 /预设 查看 名称 查看详情")
        return "\n".join(lines)

    def getPresetDetail(self, name: str) -> str:
        """获取单个预设的详细内容。"""

        content = self.presets.get(name)
        if not content:
            return f"预设不存在：{name}"
        return f"预设「{name}」的内容：\n{content}"

    def addPreset(self, name: str, content: str) -> None:
        """添加一个预设。如果已存在会覆盖。"""

        self.presets[name] = content
        self._savePresets()

    def removePreset(self, name: str) -> bool:
        """删除一个预设。返回是否删除成功。"""

        if name not in self.presets:
            return False
        del self.presets[name]
        self._savePresets()
        return True

    def _savePresets(self) -> None:
        """把当前预设写回 AstrBot 配置。"""

        self.rawConfig["presets"] = [f"{k}:{v}" for k, v in self.presets.items()]
        try:
            self.rawConfig.save_config()
        except Exception as e:
            logger.error(f"[SuperDraw] 保存预设失败: {e}")

    # ========== 模型切换 ==========

    def switchModel(self, index: int) -> str:
        """按序号切换模型（序号从 1 开始）。返回提示文字。"""

        if index < 1 or index > len(self.models):
            return "编号无效。"

        self._applyModel(self.models[index - 1]["key"])

        # 写回配置
        gen = self.rawConfig.get("generation", {})
        gen["model"] = self.currentModelKey
        self.rawConfig["generation"] = gen
        try:
            self.rawConfig.save_config()
        except Exception as e:
            logger.error(f"[SuperDraw] 保存模型配置失败: {e}")

        return f"已切换模型: {self.currentModelKey}"

    def formatModelList(self) -> str:
        """格式化模型列表，给用户看。当前选中的模型后面会打 ✅。"""

        if not self.models:
            return "无可用模型配置。"

        lines = ["可用生图模型："]
        for i, m in enumerate(self.models, 1):
            mark = " ✅" if m["key"] == self.currentModelKey else ""
            lines.append(f"  {i}. {m['key']}{mark}")
        return "\n".join(lines)
