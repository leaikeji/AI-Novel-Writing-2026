"""Bounded execution helpers for request-scoped model generation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar


CHAPTER_GENERATION_TIMEOUT_SECONDS = 300.0
CHAPTER_GENERATION_STALE_GRACE_SECONDS = 30.0


class ChapterGenerationTimeoutError(TimeoutError):
    """Raised after the chapter model call exceeds the product deadline."""


_T = TypeVar("_T")


def _consume_cancelled_task(task: asyncio.Task[object]) -> None:
    """Drain a late task result without letting it mutate authoritative data."""

    try:
        task.result()
    except BaseException:
        pass


async def await_chapter_generation(
    awaitable: Awaitable[_T],
    *,
    timeout_seconds: float = CHAPTER_GENERATION_TIMEOUT_SECONDS,
) -> _T:
    """Wait for a model reply with a hard request deadline.

    ``asyncio.wait_for`` may continue waiting when a provider coroutine ignores
    cancellation.  Waiting on the task set gives the HTTP request a real upper
    bound; a late provider result is discarded and can never reach the chapter
    completion service.
    """

    if timeout_seconds <= 0:
        raise ValueError("chapter generation timeout must be positive")
    task = asyncio.create_task(awaitable)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout_seconds)
        if task in done:
            return task.result()
        task.cancel()
        task.add_done_callback(_consume_cancelled_task)
        raise ChapterGenerationTimeoutError(
            f"等待 AI 小说作家返回超过 {int(timeout_seconds)} 秒，"
            "任务已安全结束，正式正文未修改；请检查当前 Agent 模型后重新生成。"
        )
    except BaseException:
        if not task.done():
            task.cancel()
            task.add_done_callback(_consume_cancelled_task)
        raise
