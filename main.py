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
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.star_tools import StarTools
from astrbot.core.utils.io import download_image_by_url

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
            logger.info("[SuperDraw] LLM 工具由装饰器自动注册。")
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
        # 如需精确控制，可通过 LLM 工具 super_draw 传 size/quality/n 等参数
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

    @filter.command("生图开关")
    async def cmd_toggle(self, event: AstrMessageEvent):
        newState = not self.data.enabled
        self.data.enabled = newState
        self.data.rawConfig["enabled"] = newState
        try:
            self.data.rawConfig.save_config()
        except Exception as e:
            logger.error(f"[SuperDraw] 保存配置失败: {e}")
        if not newState:
            for t in list(self._tasks.values()):
                if not t.done():
                    t.cancel()
        yield event.plain_result(f"生图功能已{'开启' if newState else '关闭'}。")

    @filter.command("生图取消")
    async def cmd_cancel(self, event: AstrMessageEvent):
        if not getattr(self.data, "enabled", True):
            return
        arg = (event.message_str or "").strip().split(maxsplit=1)[-1] if " " in (event.message_str or "") else ""
        if not arg:
            yield event.plain_result("请提供任务ID。")
            return
        tid = arg.strip()
        if tid in self._tasks:
            t = self._tasks[tid]
            if not t.done():
                t.cancel()
                self._task_meta.pop(tid, None)
                yield event.plain_result(f"任务 {tid} 已取消。")
            else:
                yield event.plain_result(f"任务 {tid} 已经跑完了。")
        else:
            yield event.plain_result(f"任务 {tid} 不存在。")

    @filter.command("预设")
    async def cmd_preset(self, event: AstrMessageEvent):
        if not getattr(self.data, "enabled", True):
            return
        text = (event.message_str or "").strip().split(maxsplit=1)[-1] if " " in (event.message_str or "") else ""
        if not text:
            yield event.plain_result(self.data.formatPresetList())
            return
        if text.startswith("查看 "):
            yield event.plain_result(self.data.getPresetDetail(text[3:].strip()))
        elif text.startswith("添加 "):
            result = self._addPreset(text[3:])
            yield event.plain_result(result)
        elif text.startswith("删除 "):
            result = self._removePreset(text[3:].strip())
            yield event.plain_result(result)
        else:
            yield event.plain_result("格式：/预设、/预设 查看 名称、/预设 添加 名称:内容、/预设 删除 名称")

    def _addPreset(self, text: str) -> str:
        if ":" not in text:
            return "格式错误：/预设 添加 名称:内容"
        name, content = text.split(":", 1)
        if not name.strip() or not content.strip():
            return "名称和内容不能为空。"
        self.data.addPreset(name.strip(), content.strip())
        return f"预设已添加：{name.strip()}"

    def _removePreset(self, name: str) -> str:
        n = name.strip()
        if not n:
            return "请提供要删除的预设名称。"
        if self.data.removePreset(n):
            return f"预设已删除：{n}"
        return f"预设不存在：{n}"

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

    @filter.llm_tool(name="super_draw")
    async def llm_draw(
        self,
        event: AstrMessageEvent,
        prompt: str,
        size: str = "auto",
        quality: str = "auto",
        n: int = 1,
        urls: str = "",
    ) -> str:
        """
        当用户想要画画、生成图片、修图、P图、改图、AI绘画时调用本工具。
        支持文生图和图生图，会自动从聊天记录中提取参考图。

        Args:
            prompt(string): 用户想要的图片内容描述，必填
            size(string): 生成图片的比例，可选 auto、1:1、16:9、9:16、3:2、2:3
            quality(string): 图片质量，可选 auto、low、medium、high
            n(integer): 生成数量，范围 1-4
            urls(string): 参考图 URL，多个地址用英文逗号分隔
        """
        if not getattr(self.data, "enabled", True):
            return "插件禁用中。"
        uid = event.unified_msg_origin
        if reason := self.data.checkUser(uid):
            return reason

        prompt = prompt.strip()
        if not prompt:
            return "请提供 prompt。"

        imgs: list[bytes] = []
        if urls:
            for u in urls.split(","):
                u = u.strip()
                if b := await self._dl(u):
                    imgs.append(b)
        imgs.extend(await self._extract_images(event))

        size = size or self.data.defaultSize
        quality = quality or self.data.defaultQuality
        n = max(1, min(4, int(n)))
        fmt = self.data.saveFormat

        tid = hashlib.md5(f"{time.time()}{uid}".encode()).hexdigest()[:8]
        self._task_meta[tid] = {"uid": uid, "prompt": prompt[:30], "time": time.time()}
        self._bg(self._do_draw(tid, uid, prompt, imgs, size, quality, fmt, n), tid)
        return f"已启动生图任务(ID:{tid})，稍后会把图片发到聊天里。"
