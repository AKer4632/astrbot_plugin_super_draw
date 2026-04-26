"""
这个文件集中处理“模型”这个主体。

用户通过 `/生图模型` 查看所有可用模型，通过 `/生图模型 2` 切换模型。切换时会先保存配置，再重建当前供应商，
这样下一次 `/生图` 会直接使用新模型。
"""

from __future__ import annotations

from astrbot.api.event import AstrMessageEvent

from .store import ImageStore


async def showOrSwitch(store: ImageStore, event: AstrMessageEvent, modelIndex: str = ""):  # 定义一个需要等待网络或文件的异步动作。
    """处理 /生图模型；无参数展示列表，有数字参数切换模型。"""
    if not store.data.currentProvider:  # 先判断这个情况，避免后面流程出错。
        yield event.plain_result("适配器还没有初始化，请先检查 API 供应商配置。")  # 这一行按当前流程执行，作用见上方说明。
        return  # 结束当前流程，不再继续往下走。

    models = store.data.getAvailableModels()  # 保存这一项数据，后面的流程会继续使用。
    if not modelIndex:  # 先判断这个情况，避免后面流程出错。
        yield event.plain_result(formatModelList(store, models))  # 这一行按当前流程执行，作用见上方说明。
        return  # 结束当前流程，不再继续往下走。

    selectedModel = pickModel(models, modelIndex)  # 保存这一项数据，后面的流程会继续使用。
    if selectedModel.startswith("错误："):  # 先判断这个情况，避免后面流程出错。
        yield event.plain_result(selectedModel)  # 这一行按当前流程执行，作用见上方说明。
        return  # 结束当前流程，不再继续往下走。

    store.data.saveCurrentModel(selectedModel)  # 这一行按当前流程执行，作用见上方说明。
    await store.changeProvider()  # 这一行按当前流程执行，作用见上方说明。
    yield event.plain_result(f"模型已切换：{selectedModel}")  # 这一行按当前流程执行，作用见上方说明。


def formatModelList(store: ImageStore, models: list[str]) -> str:  # 定义一个可重复调用的小动作。
    """把模型列表格式化成聊天消息；当前模型会标记“当前”。"""
    if not store.data.currentProvider:  # 先判断这个情况，避免后面流程出错。
        return "适配器还没有初始化。"  # 把结果交回调用者，这就是本步的反馈。
    currentModel = f"{store.data.currentProvider.name}/{store.data.currentProvider.model}"  # 保存这一项数据，后面的流程会继续使用。
    lines = ["可用模型列表："]  # 保存这一项数据，后面的流程会继续使用。
    for index, modelName in enumerate(models, 1):  # 逐个处理这组内容，避免漏掉任何一项。
        marker = "（当前）" if modelName == currentModel else ""  # 保存这一项数据，后面的流程会继续使用。
        lines.append(f"{index}. {modelName}{marker}")  # 这一行按当前流程执行，作用见上方说明。
    lines.append(f"\n当前使用：{currentModel}")  # 这一行按当前流程执行，作用见上方说明。
    return "\n".join(lines)  # 把结果交回调用者，这就是本步的反馈。


def pickModel(models: list[str], modelIndex: str) -> str:  # 定义一个可重复调用的小动作。
    """把用户输入的序号转换成模型名；序号从 1 开始。"""
    try:  # 尝试执行可能失败的外部操作。
        index = int(modelIndex) - 1  # 保存这一项数据，后面的流程会继续使用。
    except ValueError:  # 把异常变成可读的错误或日志，避免插件崩掉。
        return "错误：请输入有效的数字序号。"  # 把结果交回调用者，这就是本步的反馈。
    if index < 0 or index >= len(models):  # 先判断这个情况，避免后面流程出错。
        return "错误：无效的序号。"  # 把结果交回调用者，这就是本步的反馈。
    return models[index]  # 把结果交回调用者，这就是本步的反馈。
