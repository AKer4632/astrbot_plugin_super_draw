"""
插件的数据层。
管理配置、提供接口轮询迭代器、负责用量持久化与前缀预设解析。
"""

from __future__ import annotations

import datetime
import json
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig

from .generate import Provider


class PluginData:
    def __init__(self, config: AstrBotConfig, dataDir: Path):
        self.rawConfig = config
        self.dataDir = dataDir
        self.usageFile = dataDir / "usage.json"
        
        self.providers: list[Provider] = []
        self.models: list[dict[str, str]] = []
        self.currentModelKey: str = ""
        self.currentProviderIdx: int = 0
        
        self.maxConcurrent: int = 3
        self.defaultQuality: str = "medium"
        self.defaultSize: str = "auto"
        self.saveFormat: str = "png"
        
        self.rateLimitSeconds: int = 0
        self.enableDailyLimit: bool = False
        self.dailyLimitCount: int = 10
        
        self.maxCacheCount: int = 100
        self.cleanupIntervalHours: int = 24
        
        self.enabled: bool = True
        self.enableLLMTool: bool = True
        self.presets: dict[str, str] = {}
        
        self.usageByDate: dict[str, dict[str, int]] = {}
        self.lastReqTime: dict[str, float] = {}

        self._loadConfig()
        self._loadUsage()

    def _loadConfig(self) -> None:
        self.providers = self._parse_providers(self.rawConfig.get("api_providers", []))
        self.models = [{"key": f"{p.name}/{m}", "provider": p.name, "model": m} for p in self.providers for m in p.available_models]
        
        gen = self.rawConfig.get("generation", {})
        self.maxConcurrent = max(1, gen.get("max_concurrent_tasks", 3))
        self.defaultQuality = gen.get("default_quality", "medium")
        self.defaultSize = gen.get("default_size", "auto")
        self.saveFormat = gen.get("save_format", "png")
        self._apply_model(gen.get("model", ""))

        limits = self.rawConfig.get("user_limits", {})
        self.rateLimitSeconds = max(0, limits.get("rate_limit_seconds", 0))
        self.enableDailyLimit = limits.get("enable_daily_limit", False)
        self.dailyLimitCount = max(1, limits.get("daily_limit_count", 10))

        self.enabled = self.rawConfig.get("enabled", True)
        self.enableLLMTool = self.rawConfig.get("enable_llm_tool", True)
        
        for p in self.rawConfig.get("presets", []):
            if ":" in p:
                k, v = p.split(":", 1)
                self.presets[k.strip()] = v.strip()

    def _parse_providers(self, raw: Any) -> list[Provider]:
        out = []
        for i, rp in enumerate(raw if isinstance(raw, list) else []):
            if not isinstance(rp, dict): continue
            name = str(rp.get("name") or f"P{i+1}").strip()
            api_type = "gemini" if str(rp.get("api_type")).lower() == "gemini" else "openai"
            base_url = str(rp.get("base_url") or "").rstrip("/")
            if "/v1" in base_url: base_url = base_url.split("/v1", 1)[0].rstrip("/")
            keys = [k for k in rp.get("api_keys", []) if k]
            models = [str(m).strip() for m in rp.get("available_models", []) if str(m).strip()]
            if keys and models:
                out.append(Provider(name, api_type, keys, models[0], base_url))
                for extra in models[1:]:
                    out.append(Provider(name, api_type, keys, extra, base_url))
        return out

    def _apply_model(self, key: str) -> None:
        target = key or (self.models[0]["key"] if self.models else "")
        matched = next((m for m in self.models if m["key"] == target), self.models[0] if self.models else None)
        if not matched:
            self.currentModelKey = ""
            self.currentProviderIdx = 0
            return
        self.currentModelKey = matched["key"]
        for i, p in enumerate(self.providers):
            if p.name == matched["provider"] and p.model == matched["model"]:
                self.currentProviderIdx = i
                break

    def checkUser(self, userID: str) -> str | None:
        now = time.time()
        if self.rateLimitSeconds > 0:
            if now - self.lastReqTime.get(userID, 0) < self.rateLimitSeconds:
                return f"请等待 {int(self.rateLimitSeconds - (now - self.lastReqTime.get(userID, 0)))} 秒。"
            self.lastReqTime[userID] = now
        if self.enableDailyLimit:
            today = datetime.date.today().isoformat()
            if self.usageByDate.setdefault(today, {}).get(userID, 0) >= self.dailyLimitCount:
                return f"今日生图已达上限（{self.dailyLimitCount}次）。"
        return None

    def recordUsage(self, userID: str) -> None:
        if not self.enableDailyLimit: return
        today = datetime.date.today().isoformat()
        self.usageByDate.setdefault(today, {})[userID] = self.usageByDate[today].get(userID, 0) + 1
        try:
            self.dataDir.mkdir(parents=True, exist_ok=True)
            self.usageFile.write_text(json.dumps(self.usageByDate, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"[SuperDraw] 保存用量失败: {e}")

    def _loadUsage(self) -> None:
        if not self.usageFile.exists(): return
        try:
            self.usageByDate = json.loads(self.usageFile.read_text("utf-8"))
            today = datetime.date.today()
            keys = [k for k in self.usageByDate if (today - datetime.date.fromisoformat(k)).days > 7]
            for k in keys: del self.usageByDate[k]
        except Exception:
            self.usageByDate = {}

    def resolvePreset(self, text: str) -> tuple[str, str | None]:
        if not text: return "", None
        parts = text.split(maxsplit=1)
        name = next((k for k in self.presets if k.lower() == parts[0].lower()), None)
        if not name: return text, None
        content = self.presets[name]
        if content.startswith("{"):
            try: content = json.loads(content).get("prompt", content)
            except: pass
        extra = parts[1] if len(parts) > 1 else ""
        return f"{content} {extra}".strip(), name

    def switchModel(self, index: int) -> str:
        if index < 1 or index > len(self.models):
            return "编号无效。"
        self._apply_model(self.models[index - 1]["key"])
        gen = self.rawConfig.get("generation", {})
        gen["model"] = self.currentModelKey
        self.rawConfig["generation"] = gen
        self.rawConfig.save_config()
        return f"已切换模型: {self.currentModelKey}"

    def formatModelList(self) -> str:
        if not self.models: return "无可用模型配置。"
        lines = ["可用生图模型："]
        for i, m in enumerate(self.models, 1):
            mark = " ✅" if m["key"] == self.currentModelKey else ""
            lines.append(f"{i}. {m['key']}{mark}")
        return "\n".join(lines)
