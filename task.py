"""
这个文件写“后台任务”。

后台任务就是不用用户每次手动触发、插件自己定时做的事：清理缓存、Jimeng 领积分。
这里不生成图片，也不解析命令，只负责让这些事按时间跑起来。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

from astrbot.api import logger

from .data import ProviderType
from .provider.jimeng import Jimeng
from .store import ImageStore
from .tool.file import cleanCache


def start(store: ImageStore) -> None:  # 定义一个可重复调用的小动作。
    """插件启动时调用，开启所有后台任务。"""
    startLoop(  # 这一行按当前流程执行，作用见上方说明。
        store,  # 这一行按当前流程执行，作用见上方说明。
        "cache_cleanup",  # 这一行按当前流程执行，作用见上方说明。
        lambda: cleanCache(store.cacheDir, store.data.cacheLimit.maxCacheCount),  # 这一行按当前流程执行，作用见上方说明。
        store.data.cacheLimit.cleanupIntervalHours * 3600,  # 这一行按当前流程执行，作用见上方说明。
        True,  # 这一行按当前流程执行，作用见上方说明。
    )  # 每隔一段时间清理缓存，启动时先清一次。
    startJimengTokenTask(store)  # 如果用户配置了 Jimeng，就自动领积分。


def startJimengTokenTask(store: ImageStore) -> None:  # 定义一个可重复调用的小动作。
    """启动 Jimeng 自动领积分任务。"""
    jimengConfig = store.data.getProviderByType(ProviderType.jimeng)  # 找到 Jimeng 配置。
    if not jimengConfig:  # 先判断这个情况，避免后面流程出错。
        return  # 没配置 Jimeng 就不启动这个任务。

    jimeng = Jimeng(jimengConfig)  # 创建专门用于领积分的 Jimeng 对象。
    store.startBackground(jimeng.receiveToken(), "jimeng_token_startup")  # 插件启动后先领一次。
    startDaily(store, "jimeng_token_receive", jimeng.receiveToken, 300, False)  # 每 5 分钟检查一次是否跨天。
    logger.info("[ImageGen] 已配置 Jimeng2API 自动领积分任务：启动时一次，每日一次。")  # 这一行按当前流程执行，作用见上方说明。


def startLoop(  # 定义一个可重复调用的小动作。
    store: ImageStore,  # 这一行按当前流程执行，作用见上方说明。
    name: str,  # 这一行按当前流程执行，作用见上方说明。
    action: Callable[[], Coroutine[Any, Any, Any]],  # 这一行按当前流程执行，作用见上方说明。
    intervalSeconds: float,  # 这一行按当前流程执行，作用见上方说明。
    runImmediately: bool,  # 这一行按当前流程执行，作用见上方说明。
) -> None:  # 这一行按当前流程执行，作用见上方说明。
    """启动固定间隔任务。"""
    if name in store.loopTasks:  # 先判断这个情况，避免后面流程出错。
        store.loopTasks[name].cancel()  # 同名任务已经存在时先停掉旧的。

    async def loop() -> None:  # 定义一个需要等待网络或文件的异步动作。
        if runImmediately:  # 先判断这个情况，避免后面流程出错。
            await runSafely(name, action)  # 有些任务希望启动时马上跑一次。
        while True:  # 这一行按当前流程执行，作用见上方说明。
            try:  # 尝试执行可能失败的外部操作。
                await asyncio.sleep(intervalSeconds)  # 等到下一次执行时间。
                await runSafely(name, action)  # 执行任务主体。
            except asyncio.CancelledError:  # 把异常变成可读的错误或日志，避免插件崩掉。
                break  # 插件卸载时会取消任务，收到取消就退出循环。

    loopTask = store.startBackground(loop(), f"loop_{name}")  # 放到后台运行。
    store.loopTasks[name] = loopTask  # 记住任务，方便后面取消。


def startDaily(  # 定义一个可重复调用的小动作。
    store: ImageStore,  # 这一行按当前流程执行，作用见上方说明。
    name: str,  # 这一行按当前流程执行，作用见上方说明。
    action: Callable[[], Coroutine[Any, Any, Any]],  # 这一行按当前流程执行，作用见上方说明。
    checkIntervalSeconds: float,  # 这一行按当前流程执行，作用见上方说明。
    runImmediately: bool,  # 这一行按当前流程执行，作用见上方说明。
) -> None:  # 这一行按当前流程执行，作用见上方说明。
    """启动每天只执行一次的任务。"""

    async def dailyLoop() -> None:  # 定义一个需要等待网络或文件的异步动作。
        if runImmediately:  # 先判断这个情况，避免后面流程出错。
            await runSafely(name, action)  # 如果要求启动就执行，这里先跑一次。
        store.dailyTaskDates[name] = datetime.now().strftime("%Y-%m-%d")  # 记录今天已经处理过。
        while True:  # 这一行按当前流程执行，作用见上方说明。
            try:  # 尝试执行可能失败的外部操作。
                await asyncio.sleep(checkIntervalSeconds)  # 定期看看日期有没有变化。
                currentDate = datetime.now().strftime("%Y-%m-%d")  # 当前日期。
                if currentDate != store.dailyTaskDates.get(name):  # 先判断这个情况，避免后面流程出错。
                    await runSafely(name, action)  # 跨天后执行一次。
                    store.dailyTaskDates[name] = currentDate  # 执行成功后记录新日期。
            except asyncio.CancelledError:  # 把异常变成可读的错误或日志，避免插件崩掉。
                break  # 这一行按当前流程执行，作用见上方说明。

    store.startBackground(dailyLoop(), f"daily_{name}")  # 放到后台运行。


async def runSafely(name: str, action: Callable[[], Coroutine[Any, Any, Any]]) -> None:  # 定义一个需要等待网络或文件的异步动作。
    """执行后台动作，并把异常写进日志。"""
    try:  # 尝试执行可能失败的外部操作。
        await action()  # 执行真正的任务。
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[ImageGen] 后台任务 {name} 执行失败: {exc}", exc_info=True)  # 保存这一项数据，后面的流程会继续使用。
