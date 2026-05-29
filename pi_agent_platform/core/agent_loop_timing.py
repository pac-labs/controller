from __future__ import annotations

import asyncio
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Awaitable, Iterator, TypeVar

from .agent_events import AgentEvents

T = TypeVar("T")


@dataclass(slots=True)
class AgentLoopTiming:
    """Emit coarse timing and live progress events for user-visible stalls."""

    events: AgentEvents
    slow_seconds: float = 2.0
    heartbeat_seconds: float = 5.0
    heartbeat_start_seconds: float = 3.0
    _starts: dict[str, float] = field(default_factory=dict)

    def mark(self, phase: str, message: str, data: dict[str, Any] | None = None) -> None:
        self.events.emit("agent_phase", message, {"phase": phase, **(data or {})})

    def _payload(self, phase: str, started: float, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"phase": phase, "elapsed_ms": int((perf_counter() - started) * 1000), **(data or {})}

    async def _heartbeat(self, phase: str, message: str, started: float, data: dict[str, Any] | None = None) -> None:
        """Emit periodic progress while a long awaitable is still active.

        This is intentionally generic. Provider calls and endpoint tool calls often
        have no streaming progress, but the timeline can still show that PAC is
        alive and which phase owns the delay.
        """
        await asyncio.sleep(max(0.1, self.heartbeat_start_seconds))
        while True:
            self.events.emit("agent_phase_running", message, self._payload(phase, started, data))
            await asyncio.sleep(max(1.0, self.heartbeat_seconds))

    @contextmanager
    def phase(self, phase: str, message: str, data: dict[str, Any] | None = None) -> Iterator[None]:
        started = perf_counter()
        self.events.emit("agent_phase_started", message, {"phase": phase, **(data or {})})
        try:
            yield
        finally:
            elapsed = perf_counter() - started
            payload = {"phase": phase, "elapsed_ms": int(elapsed * 1000), **(data or {})}
            if elapsed >= self.slow_seconds:
                self.events.emit("agent_phase_slow", message, payload)
            self.events.emit("agent_phase_completed", message, payload)

    async def around_async(
        self,
        phase: str,
        message: str,
        awaitable: Awaitable[T],
        data: dict[str, Any] | None = None,
    ) -> T:
        started = perf_counter()
        emit_boundary_events = phase != "context_compaction_check"
        if emit_boundary_events:
            self.events.emit("agent_phase_started", message, {"phase": phase, **(data or {})})
        heartbeat_task = asyncio.create_task(self._heartbeat(phase, message, started, data))
        try:
            return await awaitable
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            elapsed = perf_counter() - started
            payload = {"phase": phase, "elapsed_ms": int(elapsed * 1000), **(data or {})}
            if elapsed >= self.slow_seconds:
                self.events.emit("agent_phase_slow", message, payload)
            if emit_boundary_events or elapsed >= self.slow_seconds:
                self.events.emit("agent_phase_completed", message, payload)
