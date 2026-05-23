from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


async def run_blocking_provider_call(
    func: Callable[[], T],
    *,
    timeout_seconds: int | None = None,
    on_abandoned: Callable[[], None] | None = None,
    on_late_completed: Callable[[bool], None] | None = None,
) -> T:
    """Run a blocking provider request without losing visibility on timeout.

    Python cannot forcibly terminate a blocking urllib/model-provider thread. This
    helper therefore avoids cancelling the executor future on timeout: PAC can
    continue, and the timeline can still record whether that old provider call
    eventually returned or failed.
    """
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, func)
    if not timeout_seconds or timeout_seconds <= 0:
        return await future
    done, _pending = await asyncio.wait({future}, timeout=float(timeout_seconds))
    if future in done:
        return future.result()
    if on_abandoned:
        try:
            on_abandoned()
        except Exception:
            pass

    def _late_callback(done_future: asyncio.Future) -> None:
        if not on_late_completed:
            return
        try:
            done_future.result()
            success = True
        except Exception:
            success = False
        try:
            on_late_completed(success)
        except Exception:
            pass

    future.add_done_callback(_late_callback)
    raise asyncio.TimeoutError()
