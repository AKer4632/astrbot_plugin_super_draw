"""
AstrBot 适配层：接收命令和 LLM 工具事件，调用统一生图引擎。
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.star_tools import StarTools
from astrbot.core.utils.io import download_image_by_url
from pydantic import Field
from pydantic.dataclasses import dataclass as pydantic_dataclass

from .data import PluginData
from .generate import GenerateEngine
from .tool.file import cleanCache, saveImage


class SuperDraw(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.dataDir = StarTools.get_data_dir()
        self.data = PluginData(config, self.dataDir)

        if not self.data.enabled:
            logger.info("[SuperDraw] 插件已禁用。")
            return

        self.cacheDir = self.dataDir / "cache"
        self.engine = GenerateEngine(self.data.providers, self.data.currentProviderIdx)
        self.semaphore = asyncio.Semaphore(self.data.maxConcurrent)
        self._tasks: dict[str, asyncio.Task] = {}
        self._task_meta: dict[str, dict[str, Any]] = {}

    async def initialize(self):
        if not getattr(self.data, "enabled", True):
            return
        if not self.data.providers:
            logger.error("[SuperDraw] 未配置 provider。")
        if self.data.enableLLMTool and self.data.providers:
            self.context.add_llm_tools(ImageTool(plugin=self))
            logger.info("[SuperDraw] 已注册 LLM 工具。")
        self._bg(self._cleanLoop(), "clean")
        logger.info(f"[SuperDraw] 启动，模型: {self.data.currentModelKey}")

    async def terminate(self):
        if not getattr(self.data, "enabled", True):
            return
        for t in list(self._tasks.values()):
            if not t.done():
                t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        if hasattr(self, "engine"):
            await self.engine.close()

    @filter.command("生图")
    async def cmd_draw(self, event: AstrMessageEvent):
        if not getattr(self.data, "enabled", True):
            return
        uid = event.unified_msg_origin
        if reason := self.data.checkUser(uid):
            yield event.plain_result(reason)
            return

        raw = (event.message_str or "").strip()
        body = raw.split(maxsplit=1)[-1] if " " in raw else ""
        # 普通 /生图 直接把文字和图片透传给生图模型，不做自然语言解析，避免误伤 prompt
        # 如需精确控制，可通过 LLM 工具 generate_image 传 size/quality/n 等参数
        prompt, preset = self.data.resolvePreset(body)
        if not prompt:
            yield event.plain_result("请提供提示词。")
            return

        size = self.data.defaultSize
        quality = self.data.defaultQuality
        fmt = self.data.saveFormat
        n = 1

        imgs = await self._extract_images(event)
        tid = hashlib.md5(f"{time.time()}{uid}".encode()).hexdigest()[:8]
        parts = [f"任务ID:{tid}"]
        if imgs:
            parts.append(f"参考图:{len(imgs)}")
        if preset:
            parts.append(f"预设:{preset}")
        yield event.plain_result(" ".join(parts))

        self._task_meta[tid] = {"uid": uid, "prompt": prompt[:30], "time": time.time()}
        self._bg(
            self._do_draw(tid, uid, prompt, imgs, size, quality, fmt, n),
            tid,
        )

    @filter.command("生图模型")
    async def cmd_model(self, event: AstrMessageEvent):
        if not getattr(self.data, "enabled", True):
            return
        arg = (event.message_str or "").strip().split(maxsplit=1)[-1] if " " in (event.message_str or "") else ""
        if not arg:
            yield event.plain_result(self.data.formatModelList())
        elif arg.isdigit():
            msg = self.data.switchModel(int(arg))
            self.engine.current_index = self.data.currentProviderIdx
            yield event.plain_result(msg)
        else:
            yield event.plain_result("格式: /生图模型 [数字]")

    @filter.command("生图队列")
    async def cmd_queue(self, event: AstrMessageEvent):
        if not getattr(self.data, "enabled", True):
            return
        active = [k for k, t in self._tasks.items() if not t.done()]
        if not active:
            yield event.plain_result("当前没有运行中的生图任务。")
            return
        lines = [f"运行中任务: {len(active)}"]
        for tid in active[-5:]:
            meta = self._task_meta.get(tid, {})
            elapsed = int(time.time() - meta.get("time", 0))
            lines.append(f"{tid} | {meta.get('prompt', '?')}... | {elapsed}s")
        yield event.plain_result("\n".join(lines))

    async def _do_draw(self, tid: str, uid: str, prompt: str, imgs: list[bytes], size: str, quality: str, fmt: str, n: int):
        async with self.semaphore:
            try:
                res = await self.engine.generate(prompt, imgs, size, quality, n)
                self.data.recordUsage(uid)
                chain = MessageChain()
                for b in res:
                    p = saveImage(self.cacheDir, b, fmt)
                    if p:
                        chain.file_image(p)
                await self.context.send_message(uid, chain)
            except Exception as e:
                logger.error(f"[SuperDraw] 失败: {e}")
                await self.context.send_message(uid, MessageChain().message(f"生图失败: {e}"))
            finally:
                self._task_meta.pop(tid, None)

    def _bg(self, coro, name: str):
        for done in [k for k, t in self._tasks.items() if t.done()]:
            del self._tasks[done]
        t = asyncio.create_task(coro)
        self._tasks[name] = t

    async def _cleanLoop(self):
        while True:
            try:
                await cleanCache(self.cacheDir, self.data.maxCacheCount)
                await asyncio.sleep(self.data.cleanupIntervalHours * 3600)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(60)

    async def _extract_images(self, event: AstrMessageEvent) -> list[bytes]:
        if not event.message_obj or not event.message_obj.message:
            return []
        res = []
        for i, c in enumerate(event.message_obj.message):
            if i == 0 and isinstance(c, Comp.At):
                continue
            res.extend(await self._parse_comp(c))
        # 正文里的 HTTP(S) 图片 URL 也当参考图
        text = event.message_str or ""
        for token in text.split():
            if token.startswith(("http://", "https://")) and not token.startswith("https://q4.qlogo.cn"):
                if b := await self._dl(token):
                    res.append(b)
        return res

    async def _parse_comp(self, c: Any) -> list[bytes]:
        if isinstance(c, Comp.Image):
            return [b] if (b := await self._dl(c.url or c.file)) else []
        if isinstance(c, Comp.Reply) and c.chain:
            return sum([await self._parse_comp(x) for x in c.chain], [])
        if isinstance(c, Comp.At) and str(getattr(c, "qq", "")) not in ("", "all"):
            return [b] if (b := await self._dl(f"https://q4.qlogo.cn/headimg_dl?dst_uin={c.qq}&spec=640")) else []
        if isinstance(c, Comp.Nodes):
            return sum([await self._parse_comp(n) for n in c.nodes], [])
        if isinstance(c, Comp.Node):
            return sum([await self._parse_comp(x) for x in (c.content or [])], [])
        return []

    async def _dl(self, u: str | None) -> bytes | None:
        if not u:
            return None
        try:
            if not u.startswith("http"):
                p = Path(u)
                return p.read_bytes() if p.is_file() else None
            fn = str(self.cacheDir / f"ref_{hashlib.md5(u.encode()).hexdigest()[:8]}")
            if p := await download_image_by_url(u, path=fn):
                return Path(p).read_bytes()
        except Exception:
            pass
        return None


@pydantic_dataclass
class ImageTool(FunctionTool[AstrAgentContext]):
    name: str = "generate_image"
    description: str = "调用图像生成引擎进行文生图或图生图。支持修改参考图、调整比例。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "size": {"type": "string", "enum": ["auto", "1:1", "16:9", "9:16", "3:2", "2:3", "1024x1024", "1536x1024", "1024x1536"], "default": "auto"},
                "quality": {"type": "string", "enum": ["auto", "medium", "high", "low"], "default": "auto"},
                "n": {"type": "integer", "default": 1},
                "urls": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["prompt"],
        }
    )
    is_background_task: bool = True
    plugin: Any = None

    async def call(self, context: ContextWrapper[AstrAgentContext], **kw) -> ToolExecResult:
        if not getattr(self.plugin.data, "enabled", True):
            return "插件禁用中。"
        ev = (
            context.context.event
            if hasattr(context, "context") and isinstance(context.context, AstrAgentContext)
            else context.get("event")
        )
        if not ev:
            return "无上下文。"
        uid = ev.unified_msg_origin
        if reason := self.plugin.data.checkUser(uid):
            return reason

        prompt = kw.get("prompt", "").strip()
        if not prompt:
            return "需提供 prompt。"

        imgs = []
        for u in kw.get("urls", []):
            if b := await self.plugin._dl(u):
                imgs.append(b)
        imgs.extend(await self.plugin._extract_images(ev))

        size = kw.get("size", "auto")
        quality = kw.get("quality", "auto")
        n = _to_int(str(kw.get("n", 1)), 1, 4)
        fmt = self.plugin.data.saveFormat

        tid = hashlib.md5(f"{time.time()}{uid}".encode()).hexdigest()[:8]
        self.plugin._task_meta[tid] = {"uid": uid, "prompt": prompt[:30], "time": time.time()}
        self.plugin._bg(self.plugin._do_draw(tid, uid, prompt, imgs, size, quality, fmt, n), tid)
        return "已在后台启动生图任务，预计稍后发送。"


def _to_int(value: str, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (ValueError, TypeError):
        return low
