"""
这个文件只定义 AstrBot LLM 工具。

LLM 工具不是生图业务本身，它只是另一种触发入口：读取 LLM 给的 prompt、比例、分辨率、头像引用，然后调用
image.startFromTool(...)。这样 LLM 工具和 /生图 命令共用同一套生成流程。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic.dataclasses import dataclass as pydantic_dataclass

from astrbot.api import logger
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from . import image
from .data import ImageAbility
from .store import ImageStore


@pydantic_dataclass  # 这一行按当前流程执行，作用见上方说明。
class ImageTool(FunctionTool[AstrAgentContext]):  # 定义一组放在一起的数据或行为。
    """给 LLM 调用的图像生成工具；真正生图交给 image.py。"""

    name: str = "generate_image"  # 保存这一项数据，后面的流程会继续使用。
    description: str = "使用生图模型生成或修改图片"  # 保存这一项数据，后面的流程会继续使用。
    parameters: dict = Field(
        default_factory=lambda: {  # 保存这一项数据，后面的流程会继续使用。
            "type": "object",  # 这一行按当前流程执行，作用见上方说明。
            "properties": {  # 这一行按当前流程执行，作用见上方说明。
                "prompt": {"type": "string", "description": "生图提示词。请保留用户真实意图，不要删掉关键约束。"},  # 这一行按当前流程执行，作用见上方说明。
                "aspectRatio": {"type": "string", "description": "图片宽高比；不确定时使用“自动”。", "enum": ["自动", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"], "default": "自动"},  # 这一行按当前流程执行，作用见上方说明。
                "resolution": {"type": "string", "description": "图片质量或分辨率。", "enum": ["1K", "2K", "4K"], "default": "1K"},  # 这一行按当前流程执行，作用见上方说明。
                "avatarReferences": {"type": "array", "description": "需要把头像作为参考图时填写；self 表示机器人，sender 表示发送者，也可填写 QQ 号。", "items": {"type": "string"}},  # 这一行按当前流程执行，作用见上方说明。
            },  # 这一行按当前流程执行，作用见上方说明。
            "required": ["prompt"],  # 这一行按当前流程执行，作用见上方说明。
        }
    )  # 这一行按当前流程执行，作用见上方说明。
    store: Any = None  # 保存这一项数据，后面的流程会继续使用。

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs: Any) -> ToolExecResult:  # 定义一个需要等待网络或文件的异步动作。
        """LLM 调用工具时进入这里；取出事件后启动后台生图任务。"""
        event = readEvent(context)  # 保存这一项数据，后面的流程会继续使用。
        if not event:  # 先判断这个情况，避免后面流程出错。
            logger.warning(f"[ImageGen] LLM 工具调用缺少事件上下文，context={type(context)}")  # 保存这一项数据，后面的流程会继续使用。
            return "无法获取当前消息上下文。"  # 把结果交回调用者，这就是本步的反馈。
        if not self.store:  # 先判断这个情况，避免后面流程出错。
            return "插件还没有正确初始化。"  # 把结果交回调用者，这就是本步的反馈。

        aspectRatio = kwargs.get("aspectRatio") or kwargs.get("aspect_ratio")  # 新旧参数都能读，避免旧调用方式突然失效。
        resolution = kwargs.get("resolution")  # 分辨率只有一个名字，直接交给生图流程检查。
        avatarReferences = kwargs.get("avatarReferences") or kwargs.get("avatar_references") or []  # 新旧头像参数都兼容，LLM 和旧配置都能用。
        if not isinstance(avatarReferences, list):  # 先判断这个情况，避免后面流程出错。
            avatarReferences = []  # 头像引用必须是列表，不是列表就当作没有参考头像。
        return await image.startFromTool(self.store, event, str(kwargs.get("prompt", "")).strip(), aspectRatio, resolution, avatarReferences)  # 把 LLM 触发转交给统一生图入口。


def createImageTool(store: ImageStore) -> ImageTool:  # 定义一个可重复调用的小动作。
    """创建并按当前供应商能力裁剪 LLM 工具参数。"""
    tool = ImageTool(store=store)  # 保存这一项数据，后面的流程会继续使用。
    if store.provider:  # 先判断这个情况，避免后面流程出错。
        adjustToolParameters(tool, store.provider.getAbilities())  # 这一行按当前流程执行，作用见上方说明。
    return tool  # 把结果交回调用者，这就是本步的反馈。


def adjustToolParameters(tool: ImageTool, abilities: ImageAbility) -> None:  # 定义一个可重复调用的小动作。
    """当前供应商不支持的参数不暴露给 LLM。"""
    properties = tool.parameters["properties"]  # 保存这一项数据，后面的流程会继续使用。
    if not (abilities & ImageAbility.aspectRatio):  # 先判断这个情况，避免后面流程出错。
        properties.pop("aspectRatio", None)  # 这一行按当前流程执行，作用见上方说明。
    if not (abilities & ImageAbility.resolution):  # 先判断这个情况，避免后面流程出错。
        properties.pop("resolution", None)  # 这一行按当前流程执行，作用见上方说明。
    if not (abilities & ImageAbility.imageToImage):  # 先判断这个情况，避免后面流程出错。
        properties.pop("avatarReferences", None)  # 这一行按当前流程执行，作用见上方说明。


def readEvent(context: ContextWrapper[AstrAgentContext]) -> Any:  # 定义一个可重复调用的小动作。
    """从 AstrBot 工具上下文里取当前消息事件；兼容不同包装形态。"""
    if hasattr(context, "context") and isinstance(context.context, AstrAgentContext):  # 先判断这个情况，避免后面流程出错。
        return context.context.event  # 把结果交回调用者，这就是本步的反馈。
    if isinstance(context, dict):  # 先判断这个情况，避免后面流程出错。
        return context.get("event")  # 把结果交回调用者，这就是本步的反馈。
    return None  # 把结果交回调用者，这就是本步的反馈。
