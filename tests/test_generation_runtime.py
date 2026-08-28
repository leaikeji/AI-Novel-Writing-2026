import asyncio

import pytest

from backend.generation_runtime import (
    ChapterGenerationTimeoutError,
    await_chapter_generation,
)


@pytest.mark.asyncio
async def test_chapter_generation_returns_completed_reply() -> None:
    async def complete() -> str:
        await asyncio.sleep(0)
        return "正文"

    assert await await_chapter_generation(complete(), timeout_seconds=1) == "正文"


@pytest.mark.asyncio
async def test_chapter_generation_has_a_hard_timeout_and_cancels_child() -> None:
    cancelled = asyncio.Event()

    async def hang() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with pytest.raises(ChapterGenerationTimeoutError, match="正式正文未修改"):
        await await_chapter_generation(hang(), timeout_seconds=0.01)

    await asyncio.wait_for(cancelled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_request_cancellation_cancels_model_child() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def hang() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    request_task = asyncio.create_task(
        await_chapter_generation(hang(), timeout_seconds=60)
    )
    await started.wait()
    request_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request_task
    await asyncio.wait_for(cancelled.wait(), timeout=1)
