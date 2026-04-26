"""
provider 文件夹放真实图像供应商。

image.py 只调用 createProvider(config)，不需要知道 Gemini、OpenAI、Grok 等类怎么创建。新增供应商时，在这里
补一行映射，再新增对应 provider 文件即可。
"""

from __future__ import annotations

from ..data import ProviderConfig, ProviderType
from .base import BaseProvider
from .gemini import Gemini
from .geminiOpenAI import GeminiOpenAI
from .grok import Grok
from .jimeng import Jimeng
from .openAI import OpenAI
from .zImage import ZImage


def createProvider(config: ProviderConfig) -> BaseProvider:  # 定义一个可重复调用的小动作。
    """按供应商配置创建真实供应商对象；model.py 切模型和 store 初始化都会调用。"""
    providerByType: dict[ProviderType, type[BaseProvider]] = {  # 保存这一项数据，后面的流程会继续使用。
        ProviderType.gemini: Gemini,  # 这一行按当前流程执行，作用见上方说明。
        ProviderType.geminiOpenAI: GeminiOpenAI,  # 这一行按当前流程执行，作用见上方说明。
        ProviderType.openAI: OpenAI,  # 这一行按当前流程执行，作用见上方说明。
        ProviderType.zImage: ZImage,  # 这一行按当前流程执行，作用见上方说明。
        ProviderType.jimeng: Jimeng,  # 这一行按当前流程执行，作用见上方说明。
        ProviderType.grok: Grok,  # 这一行按当前流程执行，作用见上方说明。
    }  # 这一行按当前流程执行，作用见上方说明。
    providerClass = providerByType.get(config.type)  # 保存这一项数据，后面的流程会继续使用。
    if not providerClass:  # 先判断这个情况，避免后面流程出错。
        raise ValueError(f"不支持的供应商类型: {config.type}")  # 这一行按当前流程执行，作用见上方说明。
    return providerClass(config)  # 把结果交回调用者，这就是本步的反馈。


__all__ = ["BaseProvider", "createProvider", "Gemini", "GeminiOpenAI", "OpenAI", "ZImage", "Jimeng", "Grok"]  # 保存这一项数据，后面的流程会继续使用。
