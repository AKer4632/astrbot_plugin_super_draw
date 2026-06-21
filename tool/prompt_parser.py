"""
自然语言参数解析器。

让用户像聊天一样描述需求，自动从 prompt 里提取宽高比、质量、数量、格式等参数，
并把提取出来的词从最终 prompt 中剔除，避免污染模型输入。

例如：
- "给我画一张高清竖屏的二次元少女" -> quality=high, size=9:16
- "来四张 low-poly 风格的猫 webp" -> n=4, format=webp
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class Intent:
    prompt: str
    size: str | None = None
    quality: str | None = None
    n: int | None = None
    fmt: str | None = None


_SIZE_HINTS = {
    "1:1": ["正方形", "方的", "方图", "头像", "1比1"],
    "16:9": ["横屏", "宽屏", "电脑壁纸", "16比9", "横幅"],
    "9:16": ["竖屏", "手机壁纸", "9比16", "纵向", "九比十六"],
    "3:2": ["3比2", "横向", "横图"],
    "2:3": ["2比3", "竖向", "竖长"],
    "1024x1024": ["1024方", "1024x1024"],
    "1536x1024": ["1536x1024"],
    "1024x1536": ["1024x1536"],
}

_QUALITY_HINTS = {
    "high": ["高清", "高质量", "高画质", "超清", "精细", "细致", " masterpiece ", "最佳"],
    "low": ["低清", "低质量", "草稿", "草图", "快速", " quick ", " low ", "低保真"],
    "medium": ["中等", "普通", "一般"],
}

_FMT_HINTS = {
    "webp": [" webp ", " webp格式", "转webp"],
    "jpeg": [" jpeg ", " jpg ", " jpg格式", " jpeg格式"],
    "png": [" png ", " png格式"],
}

_NUMBER_WORDS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


class PromptParser:
    """从自然语言 prompt 中抽取生图意图。"""

    @staticmethod
    def parse(text: str, defaults: dict[str, Any]) -> Intent:
        size = defaults.get("size", "auto")
        quality = defaults.get("quality", "auto")
        fmt = defaults.get("format", "png")
        n = defaults.get("n", 1)

        original = text
        stripped = text

        # 提取宽高比/尺寸
        for value, hints in _SIZE_HINTS.items():
            for h in hints:
                if h in original:
                    size = value
                    stripped = stripped.replace(h, "")
                    break

        # 提取质量
        for value, hints in _QUALITY_HINTS.items():
            for h in hints:
                if h in original:
                    quality = value
                    stripped = stripped.replace(h, "")
                    break

        # 提取格式
        for value, hints in _FMT_HINTS.items():
            for h in hints:
                if h.lower() in original.lower():
                    fmt = value
                    stripped = stripped.replace(h, "").replace(h.lower(), "")
                    break

        # 提取数量：优先 "x张", "x个", 或 "再来x张" 这种结构
        matched_n = _extract_number(original)
        if matched_n is not None:
            n = min(max(1, matched_n), 4)

        # 清理多余空格和符号
        prompt = re.sub(r"\s+", " ", stripped).strip(",.。;；!！?？ ")
        return Intent(prompt=prompt, size=size, quality=quality, n=n, fmt=fmt)


def _extract_number(text: str) -> int | None:
    """从文本里提取用户想要生成的数量。"""
    # 匹配 "来3张" "三张图" "生成四张" "给我2个" 等
    patterns = [
        r"(?:画|生成|来|给|做|搞|出)\s*([0-9一二两三四五六七八九十]+)\s*[张个幅份]",
        r"([0-9一二两三四五六七八九十]+)\s*[张个幅份]\s*(?:图|画|照片|风格)",
    ]
    for pat in patterns:
        if m := re.search(pat, text):
            token = m.group(1)
            return _token_to_int(token)
    return None


def _token_to_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    # 简单处理中文数字，只支持单个字
    if len(token) == 1 and token in _NUMBER_WORDS:
        return _NUMBER_WORDS[token]
    return None
