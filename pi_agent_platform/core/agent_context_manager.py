from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .config import AppConfig
from .context_manager import ContextBudget, compact_messages_basic, get_context_budget, message_tokens, truncate_middle
from .models import Session, Task
from .agent_events import AgentEvents
from .store import store


DEFAULT_CHECKPOINT_FRACTION = 0.65
DEFAULT_COMPACTION_FRACTION = 0.80
RECENT_MESSAGE_WINDOW = 12
CHECKPOINT_SUMMARY_TIMEOUT_SECONDS = 25


@dataclass(frozen=True)
class ContextCompactionReport:
    before_tokens: int
    after_tokens: int
    budget_tokens: int
    input_budget_tokens: int
    source: str
    forced: bool = False


@dataclass(frozen=True)
class ContextPressureReport:
    tokens: int
    input_budget_tokens: int
    checkpoint_threshold_tokens: int
    compaction_threshold_tokens: int
    fraction: float
    level: str
    source: str
    step: int | None = None


class AgentContextManager:
    """Owns runtime context pressure checks, checkpoint summaries, and compaction."""

    def __init__(
        self,
        session: Session,
        task: Task,
        config: AppConfig,
        *,
        model_name: str,
        context_profile: str | None,
        checkpoint_fraction: float = DEFAULT_CHECKPOINT_FRACTION,
        compaction_fraction: float = DEFAULT_COMPACTION_FRACTION,
    ) -> None:
        self.session = session
        self.task = task
        self.config = config
        self.model_name = model_name
        self.context_profile = context_profile
        self.budget: ContextBudget = get_context_budget(config, model_name, context_profile)
        self.checkpoint_fraction = max(0.25, min(0.95, checkpoint_fraction))
        self.compaction_fraction = max(self.checkpoint_fraction + 0.05, min(0.98, compaction_fraction))
        self.rolling_summary: str | None = task.metadata.get("rolling_context_summary")
        self.events = AgentEvents(session, task)

    @property
    def input_budget_tokens(self) -> int:
        return self.budget.input_budget_tokens

    @property
    def checkpoint_threshold_tokens(self) -> int:
        return int(self.input_budget_tokens * self.checkpoint_fraction)

    @property
    def threshold_tokens(self) -> int:
        return self.compaction_threshold_tokens

    @property
    def compaction_threshold_tokens(self) -> int:
        return int(self.input_budget_tokens * self.compaction_fraction)

    def estimate_messages(self, messages: list[dict[str, str]]) -> int:
        return message_tokens(messages)

    def consume_compact_now_request(self) -> bool:
        requested = bool(self.task.metadata.pop("_compact_now", False))
        if requested:
            store.add_task(self.task)
        return requested

    def consume_checkpoint_request(self) -> bool:
        requested = bool(self.task.metadata.pop("_context_checkpoint_due", False))
        if requested:
            store.add_task(self.task)
        return requested

    async def manage_pressure(
        self,
        messages: list[dict[str, str]],
        *,
        source: str = "threshold",
        step: int | None = None,
        force_checkpoint: bool = False,
        force_compact: bool = False,
    ) -> list[dict[str, str]]:
        """Emit context pressure, checkpoint at 65%, and compact at 80%."""
        tokens = self.estimate_messages(messages)
        self._record_estimate(tokens)
        report = self._pressure_report(tokens, source=source, step=step)
        self._emit_pressure_if_changed(report)

        if force_checkpoint or tokens >= self.checkpoint_threshold_tokens:
            await self._ensure_checkpoint_summary(messages, tokens=tokens, source=source, step=step, forced=force_checkpoint)

        if force_compact or tokens >= self.compaction_threshold_tokens:
            return await self.maybe_compact(messages, source=source, force=True)
        return messages

    async def maybe_compact(
        self,
        messages: list[dict[str, str]],
        *,
        source: str = "threshold",
        force: bool = False,
    ) -> list[dict[str, str]]:
        """Compact messages if the input budget is pressured, or immediately when forced."""
        before_tokens = self.estimate_messages(messages)
        if not force and before_tokens < self.compaction_threshold_tokens:
            self._record_estimate(before_tokens)
            return messages

        # Prefer the model-generated checkpoint summary as the rolling compaction
        # anchor. Basic compaction still works as a fallback when model summary
        # generation is unavailable.
        checkpoint_summary = str(self.task.metadata.get("context_checkpoint_summary") or "").strip()
        base_summary = checkpoint_summary or self.rolling_summary
        compacted_messages, rolling_summary, did_compact = compact_messages_basic(
            messages,
            self.budget,
            base_summary,
        )
        if not did_compact:
            self._record_estimate(before_tokens)
            return messages

        self.rolling_summary = rolling_summary
        after_tokens = self.estimate_messages(compacted_messages)
        self.task.metadata["rolling_context_summary"] = rolling_summary
        self.task.metadata["context_tokens_estimate"] = after_tokens
        self.task.metadata["context_last_compacted_at_step"] = self.task.metadata.get("agent_step")
        store.add_task(self.task)
        self._emit_compaction_event(
            ContextCompactionReport(
                before_tokens=before_tokens,
                after_tokens=after_tokens,
                budget_tokens=self.budget.budget_tokens,
                input_budget_tokens=self.input_budget_tokens,
                source=source,
                forced=force,
            )
        )
        return compacted_messages

    def keep_recent_window(
        self,
        messages: list[dict[str, str]],
        *,
        recent_count: int = RECENT_MESSAGE_WINDOW,
    ) -> list[dict[str, str]]:
        """Keep stable anchor messages plus a recent tail after tool execution."""
        if len(messages) <= recent_count + 2:
            self._record_estimate(self.estimate_messages(messages))
            return messages
        replaced = messages[:2] + messages[-recent_count:]
        self._record_estimate(self.estimate_messages(replaced))
        return replaced

    def restore_checkpoint_summary_into_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """Inject the latest checkpoint summary into a resumed active loop once."""
        if self.task.metadata.get("context_checkpoint_restored"):
            return messages
        summary = str(self.task.metadata.get("context_checkpoint_summary") or "").strip()
        if not summary:
            return messages
        restored = [
            *messages[:2],
            {
                "role": "system",
                "content": "Restored PAC context checkpoint summary. Use this as compressed continuity for the active loop.\n\n" + summary,
            },
            *messages[2:],
        ]
        self.task.metadata["context_checkpoint_restored"] = True
        store.add_task(self.task)
        self.events.context_checkpoint_restored(summary_tokens=max(1, len(summary) // 4))
        return restored

    def _pressure_report(self, tokens: int, *, source: str, step: int | None) -> ContextPressureReport:
        budget = max(1, self.input_budget_tokens)
        fraction = tokens / budget
        if tokens >= self.compaction_threshold_tokens:
            level = "compact"
        elif tokens >= self.checkpoint_threshold_tokens:
            level = "checkpoint"
        elif fraction >= 0.5:
            level = "watch"
        else:
            level = "ok"
        return ContextPressureReport(
            tokens=tokens,
            input_budget_tokens=budget,
            checkpoint_threshold_tokens=self.checkpoint_threshold_tokens,
            compaction_threshold_tokens=self.compaction_threshold_tokens,
            fraction=fraction,
            level=level,
            source=source,
            step=step,
        )

    def _emit_pressure_if_changed(self, report: ContextPressureReport) -> None:
        last = self.task.metadata.get("context_pressure_last") or {}
        # Avoid noisy event spam: emit on level changes and around 5% movement.
        last_level = str(last.get("level") or "")
        last_percent = int(last.get("percent") or -1)
        percent = int(report.fraction * 100)
        if last_level == report.level and abs(percent - last_percent) < 5:
            return
        self.task.metadata["context_pressure_last"] = {
            "level": report.level,
            "percent": percent,
            "tokens": report.tokens,
            "input_budget_tokens": report.input_budget_tokens,
            "step": report.step,
        }
        self.task.metadata["context_tokens_estimate"] = report.tokens
        self.session.metadata["context_budget"] = {
            "tokens": report.tokens,
            "input_budget_tokens": report.input_budget_tokens,
            "checkpoint_threshold_tokens": report.checkpoint_threshold_tokens,
            "compaction_threshold_tokens": report.compaction_threshold_tokens,
            "percent": percent,
            "level": report.level,
        }
        store.add_task(self.task)
        store.add_session(self.session)
        self.events.context_pressure(
            tokens=report.tokens,
            input_budget_tokens=report.input_budget_tokens,
            checkpoint_threshold_tokens=report.checkpoint_threshold_tokens,
            compaction_threshold_tokens=report.compaction_threshold_tokens,
            fraction=report.fraction,
            level=report.level,
            source=report.source,
            step=report.step,
        )

    async def _ensure_checkpoint_summary(
        self,
        messages: list[dict[str, str]],
        *,
        tokens: int,
        source: str,
        step: int | None,
        forced: bool = False,
    ) -> None:
        signature = self._message_signature(messages)
        if not forced and self.task.metadata.get("context_checkpoint_signature") == signature:
            return
        summary = await self._generate_checkpoint_summary(messages)
        self.task.metadata["context_checkpoint_summary"] = summary
        self.task.metadata["context_checkpoint_signature"] = signature
        self.task.metadata["context_checkpoint_tokens"] = tokens
        self.task.metadata["context_checkpoint_step"] = step
        self.task.metadata["_context_checkpoint_due"] = True
        # Make the summary immediately available to future compaction even if the
        # process exits before the next compaction threshold.
        self.rolling_summary = summary
        self.task.metadata["rolling_context_summary"] = summary
        store.add_task(self.task)
        self.events.context_checkpoint_summary(
            step=step,
            tokens=tokens,
            input_budget_tokens=self.input_budget_tokens,
            threshold_tokens=self.checkpoint_threshold_tokens,
            source=source,
            summary=summary,
            forced=forced,
        )

    async def _generate_checkpoint_summary(self, messages: list[dict[str, str]]) -> str:
        summary_input = self._summarize_messages_for_checkpoint(messages)
        prompt = (
            "Create a compact PAC agent checkpoint summary for resuming this coding/session loop. "
            "Preserve: user goal, constraints, verified file paths, tool results, decisions, pending approvals, "
            "open risks, next best action, and any work already changed. Do not add speculation."
        )
        model_messages = [
            {
                "role": "system",
                "content": "You write concise, factual checkpoint summaries for long-running agent sessions.",
            },
            {"role": "user", "content": prompt + "\n\nSESSION CONTEXT:\n" + summary_input},
        ]
        try:
            from .agent_model_calls import run_blocking_provider_call
            from .providers import chat_complete

            result = await run_blocking_provider_call(
                lambda: chat_complete(self.config, self.model_name, model_messages, max_tokens=900),
                timeout_seconds=CHECKPOINT_SUMMARY_TIMEOUT_SECONDS,
            )
            text = str(result or "").strip()
            if text:
                return truncate_middle(text, 900)
        except Exception as exc:
            self.events.context_checkpoint_summary_failed(str(exc))
        return self._fallback_checkpoint_summary(messages)

    def _summarize_messages_for_checkpoint(self, messages: list[dict[str, str]]) -> str:
        parts: list[str] = []
        if self.rolling_summary:
            parts.append("PREVIOUS SUMMARY:\n" + truncate_middle(self.rolling_summary, 900))
        for item in messages[-18:]:
            role = str(item.get("role") or "message")
            content = truncate_middle(str(item.get("content") or ""), 900)
            if content:
                parts.append(f"{role}: {content}")
        return "\n\n".join(parts)

    def _fallback_checkpoint_summary(self, messages: list[dict[str, str]]) -> str:
        text = self._summarize_messages_for_checkpoint(messages)
        return truncate_middle("Fallback checkpoint summary from recent session context:\n" + text, 1000)

    def _message_signature(self, messages: list[dict[str, str]]) -> str:
        digest = hashlib.sha1()
        for item in messages[-24:]:
            digest.update(str(item.get("role") or "").encode("utf-8", errors="ignore"))
            digest.update(b"\0")
            digest.update(str(item.get("content") or "")[:4000].encode("utf-8", errors="ignore"))
            digest.update(b"\0")
        return digest.hexdigest()[:16]

    def _record_estimate(self, tokens: int) -> None:
        if self.task.metadata.get("context_tokens_estimate") == tokens:
            return
        self.task.metadata["context_tokens_estimate"] = tokens
        store.add_task(self.task)

    def _emit_compaction_event(self, report: ContextCompactionReport) -> None:
        self.events.context_compacted(
            before_tokens=report.before_tokens,
            after_tokens=report.after_tokens,
            budget_tokens=report.budget_tokens,
            input_budget_tokens=report.input_budget_tokens,
            source=report.source,
            forced=report.forced,
        )
