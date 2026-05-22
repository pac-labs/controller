from __future__ import annotations

from dataclasses import dataclass
from .config import AppConfig
from .context_manager import ContextBudget, compact_messages_basic, get_context_budget, message_tokens
from .models import Session, Task
from .agent_events import AgentEvents
from .store import store


DEFAULT_COMPACTION_FRACTION = 0.82
RECENT_MESSAGE_WINDOW = 12


@dataclass(frozen=True)
class ContextCompactionReport:
    before_tokens: int
    after_tokens: int
    budget_tokens: int
    input_budget_tokens: int
    source: str
    forced: bool = False


class AgentContextManager:
    """Owns runtime context pressure checks and message compaction for an agent run."""

    def __init__(
        self,
        session: Session,
        task: Task,
        config: AppConfig,
        *,
        model_name: str,
        context_profile: str | None,
        compaction_fraction: float = DEFAULT_COMPACTION_FRACTION,
    ) -> None:
        self.session = session
        self.task = task
        self.config = config
        self.model_name = model_name
        self.context_profile = context_profile
        self.budget: ContextBudget = get_context_budget(config, model_name, context_profile)
        self.compaction_fraction = max(0.25, min(0.95, compaction_fraction))
        self.rolling_summary: str | None = task.metadata.get("rolling_context_summary")
        self.events = AgentEvents(session, task)

    @property
    def input_budget_tokens(self) -> int:
        return self.budget.input_budget_tokens

    @property
    def threshold_tokens(self) -> int:
        return int(self.input_budget_tokens * self.compaction_fraction)

    def estimate_messages(self, messages: list[dict[str, str]]) -> int:
        return message_tokens(messages)

    def consume_compact_now_request(self) -> bool:
        requested = bool(self.task.metadata.pop("_compact_now", False))
        if requested:
            store.add_task(self.task)
        return requested

    async def maybe_compact(
        self,
        messages: list[dict[str, str]],
        *,
        source: str = "threshold",
        force: bool = False,
    ) -> list[dict[str, str]]:
        """Compact messages if the input budget is pressured, or immediately when forced."""
        before_tokens = self.estimate_messages(messages)
        if not force and before_tokens <= self.threshold_tokens:
            self._record_estimate(before_tokens)
            return messages

        compacted_messages, rolling_summary, did_compact = compact_messages_basic(
            messages,
            self.budget,
            self.rolling_summary,
        )
        if not did_compact:
            self._record_estimate(before_tokens)
            return messages

        self.rolling_summary = rolling_summary
        after_tokens = self.estimate_messages(compacted_messages)
        self.task.metadata["rolling_context_summary"] = rolling_summary
        self.task.metadata["context_tokens_estimate"] = after_tokens
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
