from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .llmfit import llmfit_recommendations

if TYPE_CHECKING:
    from .config import AppConfig
    from .models import Session, Task


_CACHE_TTL_SECONDS = 300.0
_LLMFIT_CACHE: dict[tuple[str, int | None], tuple[float, dict[str, float]]] = {}


def coding_model_scores(
    config: AppConfig,
    session: Session,
    task: Task,
    candidate_names: list[str],
) -> dict[str, float]:
    scores = {name: _heuristic_coding_score(config, session, name) for name in candidate_names}
    llmfit_scores = _llmfit_scores(config, session)
    for name in candidate_names:
        scores[name] = scores.get(name, 0.0) + llmfit_scores.get(name, 0.0)
    return scores


def order_coding_candidates(
    config: AppConfig,
    session: Session,
    task: Task,
    candidate_names: list[str],
) -> list[str]:
    scores = coding_model_scores(config, session, task, candidate_names)
    return sorted(candidate_names, key=lambda name: (scores.get(name, float("-inf")), name), reverse=True)


def should_escalate_after_validation_failures(task: Task, *, threshold: int = 3) -> bool:
    history = list((task.metadata or {}).get("doom_loop_history") or [])
    failures = [item for item in history[-8:] if str(item.get("outcome") or "") == "validation_fail"]
    return len(failures) >= threshold


def _heuristic_coding_score(config: AppConfig, session: Session, model_name: str) -> float:
    model = config.models.get(str(model_name or "").strip())
    if not model:
        return -1000.0
    provider = config.providers.get(model.provider)
    caps = getattr(model, "capabilities", None)
    text_parts = [
        model_name.lower(),
        str(model.display_name or "").lower(),
        str(model.model or "").lower(),
        str(model.provider or "").lower(),
        str((provider.type if provider else "") or "").lower(),
    ]
    joined = " ".join(text_parts)
    score = 0.0
    if "embed" in joined or "embedding" in joined:
        return -1000.0
    if "vision" in joined:
        score -= 30.0
    if "coder" in joined or "coding" in joined or "code" in joined:
        score += 40.0
    if "instruct" in joined or "chat" in joined:
        score += 12.0
    if "reason" in joined or "nemotron" in joined or "qwen" in joined:
        score += 8.0
    if "flash" in joined or "nano" in joined or "tiny" in joined:
        score -= 6.0
    if caps:
        if getattr(caps, "supports_tools", False):
            score += 12.0
        if getattr(caps, "supports_json", False):
            score += 8.0
        score += {
            "none": 0.0,
            "low": 2.0,
            "medium": 6.0,
            "high": 10.0,
        }.get(str(getattr(caps, "reasoning", "none") or "none"), 0.0)
    score += min(float(model.context_window or 0) / 8192.0, 8.0)
    preferred_endpoint = str((session.metadata or {}).get("preferred_endpoint") or "").strip()
    if preferred_endpoint and str(model.runs_on or "").strip() == preferred_endpoint:
        score += 5.0
    return score


def _llmfit_scores(config: AppConfig, session: Session) -> dict[str, float]:
    max_context = None
    try:
        max_context = max(int(item.context_window or 0) for item in config.models.values()) or None
    except Exception:
        max_context = None
    cache_key = ("coding", max_context)
    cached = _LLMFIT_CACHE.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    result = llmfit_recommendations(
        use_case="coding",
        limit=8,
        max_context=max_context,
        force_runtime=_preferred_runtime_hint(config, session),
        timeout_seconds=3.0,
    )
    mapping: dict[str, float] = {}
    if result.get("ok"):
        recommendations = result.get("recommendations") or []
        for index, item in enumerate(recommendations):
            if not isinstance(item, dict):
                continue
            raw_name = str(item.get("name") or "").strip().lower()
            if not raw_name:
                continue
            bonus = 24.0 - float(index * 3)
            for model_name, model in config.models.items():
                aliases = {
                    str(model_name or "").strip().lower(),
                    str(model.display_name or "").strip().lower(),
                    str(model.model or "").strip().lower(),
                }
                if raw_name in aliases or any(raw_name and raw_name in alias for alias in aliases if alias):
                    mapping[model_name] = max(mapping.get(model_name, float("-inf")), bonus)
    _LLMFIT_CACHE[cache_key] = (now, mapping)
    return mapping


def _preferred_runtime_hint(config: AppConfig, session: Session) -> str | None:
    preferred_endpoint = str((session.metadata or {}).get("preferred_endpoint") or "").strip()
    if not preferred_endpoint:
        return None
    runner = getattr(config, "runners", {}).get(preferred_endpoint) if hasattr(config, "runners") else None
    if runner and getattr(runner, "metadata", None):
        runtime = str((runner.metadata or {}).get("runtime") or "").strip().lower()
        if runtime:
            return runtime
    return None
