from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class AgentModelCallAborted(RuntimeError):
    """Raised when PAC abandons a blocking provider call because the task stopped."""


def _attach_late_callback(
    future: asyncio.Future,
    on_late_completed: Callable[[bool], None] | None,
) -> None:
    if not on_late_completed:
        return

    def _late_callback(done_future: asyncio.Future) -> None:
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


async def run_blocking_provider_call(
    func: Callable[[], T],
    *,
    timeout_seconds: int | None = None,
    on_abandoned: Callable[[], None] | None = None,
    on_late_completed: Callable[[bool], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
    on_aborted: Callable[[], None] | None = None,
    poll_seconds: float = 1.0,
) -> T:
    """Run a blocking provider request while preserving PAC control.

    The model/provider clients are synchronous and may block inside urllib. Python
    cannot forcibly kill that thread. PAC therefore waits in short slices so a
    stop/cancel request or a wall-clock timeout can abandon the task quickly while
    the old provider call is left to finish in the background.
    """
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, func)
    started = loop.time()
    timeout_at = started + float(timeout_seconds) if timeout_seconds and timeout_seconds > 0 else None
    poll = max(0.2, float(poll_seconds or 1.0))

    while True:
        if should_abort and should_abort():
            _attach_late_callback(future, on_late_completed)
            if on_aborted:
                try:
                    on_aborted()
                except Exception:
                    pass
            raise AgentModelCallAborted("Provider call abandoned because the task was stopped.")

        wait_for = poll
        if timeout_at is not None:
            remaining = timeout_at - loop.time()
            if remaining <= 0:
                _attach_late_callback(future, on_late_completed)
                if on_abandoned:
                    try:
                        on_abandoned()
                    except Exception:
                        pass
                raise asyncio.TimeoutError()
            wait_for = min(wait_for, remaining)

        done, _pending = await asyncio.wait({future}, timeout=wait_for)
        if future in done:
            return future.result()
