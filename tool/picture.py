"""
这个文件放“图片格式”小工具。

它只判断图片是什么格式，以及在供应商不认识某种格式时，把图片转成更常见的 JPEG。
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from io import BytesIO

from PIL import Image

from astrbot.api import logger

from ..data import PictureData

supportedImageFormats = {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}  # 供应商通常能接受的格式。


def detectMimeType(data: bytes) -> str:  # 定义一个可重复调用的小动作。
    """看图片开头的字节，猜图片格式。"""
    if data.startswith(b"\xff\xd8"):  # 先判断这个情况，避免后面流程出错。
        return "image/jpeg"  # JPEG 文件通常以 FF D8 开头。
    if data.startswith(b"\x89PNG\r\n\x1a\n"):  # 先判断这个情况，避免后面流程出错。
        return "image/png"  # PNG 文件有固定开头。
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):  # 先判断这个情况，避免后面流程出错。
        return "image/gif"  # GIF 有两个常见版本头。
    if len(data) > 12 and data[4:8] == b"ftyp":  # 先判断这个情况，避免后面流程出错。
        brand = data[8:12]  # HEIC/HEIF 会把格式标记放在这里。
        if brand in (b"heic", b"heix", b"heim", b"heis"):  # 先判断这个情况，避免后面流程出错。
            return "image/heic"  # 把结果交回调用者，这就是本步的反馈。
        if brand in (b"mif1", b"msf1", b"heif"):  # 先判断这个情况，避免后面流程出错。
            return "image/heif"  # 把结果交回调用者，这就是本步的反馈。
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":  # 先判断这个情况，避免后面流程出错。
        return "image/webp"  # WEBP 是 RIFF 容器。
    return "application/octet-stream"  # 识别不到就返回通用二进制。


async def convertPicture(data: bytes, mimeType: str) -> PictureData:  # 定义一个需要等待网络或文件的异步动作。
    """必要时把图片转成 JPEG。"""
    realMime = detectMimeType(data)  # 不完全相信外部传进来的格式，自己再判断一次。
    if realMime in supportedImageFormats:  # 先判断这个情况，避免后面流程出错。
        return PictureData(data=data, mimeType=realMime)  # 已经是常见格式就原样返回。
    logger.info(f"[ImageGen] 正在转换图片格式: {mimeType} -> image/jpeg")  # 这一行按当前流程执行，作用见上方说明。
    return await asyncio.to_thread(convertPictureSync, data, mimeType)  # Pillow 会阻塞，所以放到线程里跑。


async def convertPictures(pictures: Iterable[PictureData]) -> list[PictureData]:  # 定义一个需要等待网络或文件的异步动作。
    """批量转换图片。"""
    return await asyncio.gather(*[convertPicture(picture.data, picture.mimeType) for picture in pictures])  # 多张图并行处理。


def convertPictureSync(data: bytes, mimeType: str) -> PictureData:  # 定义一个可重复调用的小动作。
    """同步转换一张图片。"""
    try:  # 尝试执行可能失败的外部操作。
        image = Image.open(BytesIO(data))  # 从字节打开图片。
        if image.mode in ("RGBA", "LA", "P"):  # 先判断这个情况，避免后面流程出错。
            background = Image.new("RGB", image.size, (255, 255, 255))  # JPEG 没有透明通道，所以先铺白底。
            if image.mode in ("P", "LA"):  # 先判断这个情况，避免后面流程出错。
                image = image.convert("RGBA")  # 调色板图先转成带透明通道的格式。
            background.paste(image, mask=image.split()[3])  # 用透明通道当遮罩，把图贴到白底上。
            image = background  # 保存这一项数据，后面的流程会继续使用。
        output = BytesIO()  # 用内存保存转换后的图片。
        image.save(output, format="JPEG", quality=95)  # 95 质量比较清楚，文件也不会太夸张。
        return PictureData(data=output.getvalue(), mimeType="image/jpeg")  # 把结果交回调用者，这就是本步的反馈。
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[ImageGen] 图片转换失败: {exc}")  # 这一行按当前流程执行，作用见上方说明。
        return PictureData(data=data, mimeType=mimeType)  # 转换失败就原样返回，让供应商自己试。
