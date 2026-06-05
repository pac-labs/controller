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
    return validation_failure_count(task) >= threshold


def validation_failure_count(task: Task, *, window: int = 8) -> int:
    history = list((task.metadata or {}).get("doom_loop_history") or [])
    failures = [item for item in history[-window:] if str(item.get("outcome") or "") == "validation_fail"]
    return len(failures)


def should_prompt_for_model_upgrade(task: Task, *, fallback_used: bool, threshold: int = 5) -> bool:
    metadata = task.metadata or {}
    if metadata.get("model_upgrade_prompted"):
        return False
    return fallback_used and validation_failure_count(task, window=12) >= threshold


def recommend_coding_model_upgrade(
    config: AppConfig,
    session: Session,
    task: Task,
    *,
    current_models: list[str],
) -> dict[str, object]:
    llmfit_result = llmfit_recommendations(
        use_case="coding",
        limit=5,
        max_context=_max_context(config),
        force_runtime=_preferred_runtime_hint(config, session),
        timeout_seconds=3.0,
    )
    candidates = _llmfit_candidates(config, llmfit_result, current_models=current_models)
    source = "llmfit" if candidates else "heuristic"
    if not candidates:
        candidates = _heuristic_inventory_candidates(config, session, current_models=current_models)
    return {
        "ok": bool(candidates),
        "source": source,
        "llmfit": llmfit_result,
        "candidates": candidates,
    }


def build_model_upgrade_message(
    recommendation: dict[str, object],
    *,
    current_models: list[str],
    failure_count: int,
) -> str:
    lines = [
        "The current local coding models are underperforming on this task.",
        f"PAC has already hit {failure_count} validation failure(s) while trying {', '.join(current_models) or 'the current model'}.",
        "",
    ]
    llmfit_result = recommendation.get("llmfit") if isinstance(recommendation, dict) else None
    source = str(recommendation.get("source") or "heuristic") if isinstance(recommendation, dict) else "heuristic"
    if source == "llmfit":
        lines.append("These better-fit local coding candidates come from llmfit:")
    else:
        error = ""
        if isinstance(llmfit_result, dict) and llmfit_result.get("installed") and not llmfit_result.get("ok"):
            error = str(llmfit_result.get("error") or llmfit_result.get("reason") or "").strip()
        if error:
            lines.append(f"llmfit could not be used here ({error}), so PAC fell back to local provider inventory heuristics.")
        else:
            lines.append("PAC fell back to local provider inventory heuristics for better-fit coding models.")
        lines.append("Suggested local coding candidates:")
    candidates = recommendation.get("candidates") if isinstance(recommendation, dict) else []
    for index, item in enumerate(candidates or [], start=1):
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider_name") or "").strip()
        model_id = str(item.get("provider_model_id") or item.get("name") or "").strip()
        configured = str(item.get("configured_model_name") or "").strip()
        memory = item.get("memory_gb")
        note_bits: list[str] = []
        if configured:
            note_bits.append(f"already configurable as {configured}")
        else:
            note_bits.append("not configured in PAC yet")
        if memory:
            note_bits.append(f"{memory} GB device memory")
        lines.append(f"{index}. {provider} -> {model_id} ({'; '.join(note_bits)})")
    if not candidates:
        lines.append("No better local candidate could be identified from the currently visible provider inventories.")
    lines.append("")
    lines.append("Should PAC download/configure a better-fit model and switch this coding session to it?")
    return "\n".join(lines)


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
    max_context = _max_context(config)
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


def _max_context(config: AppConfig) -> int | None:
    try:
        return max(int(item.context_window or 0) for item in config.models.values()) or None
    except Exception:
        return None


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


def _llmfit_candidates(
    config: AppConfig,
    result: dict[str, object],
    *,
    current_models: list[str],
) -> list[dict[str, object]]:
    if not isinstance(result, dict) or not result.get("ok"):
        return []
    names = {str(name or "").strip().lower() for name in current_models}
    candidates: list[dict[str, object]] = []
    for item in result.get("recommendations") or []:
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name") or "").strip()
        if not raw_name or raw_name.lower() in names or "embed" in raw_name.lower():
            continue
        for provider_name, provider_model_id, configured_name, memory_gb in _matching_provider_models(config, raw_name):
            candidates.append(
                {
                    "name": raw_name,
                    "provider_name": provider_name,
                    "provider_model_id": provider_model_id,
                    "configured_model_name": configured_name,
                    "memory_gb": memory_gb,
                    "source": "llmfit",
                }
            )
    return _dedupe_candidates(candidates)[:3]


def _heuristic_inventory_candidates(
    config: AppConfig,
    session: Session,
    *,
    current_models: list[str],
) -> list[dict[str, object]]:
    current_names = {str(name or "").strip().lower() for name in current_models}
    candidates: list[dict[str, object]] = []
    for provider_name, provider in config.providers.items():
        if str(getattr(provider, "type", "") or "").lower() != "lmstudio" or getattr(provider, "enabled", True) is False:
            continue
        runtime = getattr(provider, "runtime", None) or {}
        device = runtime.get("device") if isinstance(runtime, dict) else {}
        memory_gb = None
        try:
            memory_gb = float(device.get("memory_gb")) if isinstance(device, dict) and device.get("memory_gb") is not None else None
        except Exception:
            memory_gb = None
        for item in getattr(provider, "cached_models", []) or []:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or item.get("name") or "").strip()
            lowered = model_id.lower()
            if not model_id or lowered in current_names or "embed" in lowered:
                continue
            score = _inventory_score(lowered, memory_gb)
            if score <= 0:
                continue
            configured_name = _configured_model_name(config, provider_name, model_id)
            candidates.append(
                {
                    "name": model_id,
                    "provider_name": provider_name,
                    "provider_model_id": model_id,
                    "configured_model_name": configured_name,
                    "memory_gb": memory_gb,
                    "source": "heuristic",
                    "score": score,
                }
            )
    deduped = _dedupe_candidates(candidates)
    return sorted(deduped, key=lambda item: float(item.get("score") or 0.0), reverse=True)[:3]


def _inventory_score(model_id: str, memory_gb: float | None) -> float:
    score = 0.0
    if "coder" in model_id or "coding" in model_id or "qwen" in model_id:
        score += 20.0
    if "27b" in model_id or "32b" in model_id or "34b" in model_id:
        score += 18.0
    if "14b" in model_id or "12b" in model_id:
        score += 10.0
    if "gemma" in model_id:
        score += 8.0
    if "nemotron" in model_id and "nano" in model_id:
        score -= 4.0
    if "tiny" in model_id or "flash" in model_id:
        score -= 8.0
    if memory_gb and memory_gb >= 20:
        score += 8.0
    elif memory_gb and memory_gb < 10:
        score -= 4.0
    return score


def _matching_provider_models(config: AppConfig, raw_name: str) -> list[tuple[str, str, str | None, float | None]]:
    matches: list[tuple[str, str, str | None, float | None]] = []
    lowered = raw_name.lower()
    for provider_name, provider in config.providers.items():
        if str(getattr(provider, "type", "") or "").lower() != "lmstudio":
            continue
        runtime = getattr(provider, "runtime", None) or {}
        device = runtime.get("device") if isinstance(runtime, dict) else {}
        memory_gb = None
        try:
            memory_gb = float(device.get("memory_gb")) if isinstance(device, dict) and device.get("memory_gb") is not None else None
        except Exception:
            memory_gb = None
        for item in getattr(provider, "cached_models", []) or []:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or item.get("name") or "").strip()
            if not model_id:
                continue
            alias = model_id.lower()
            if lowered == alias or lowered in alias or alias in lowered:
                matches.append((provider_name, model_id, _configured_model_name(config, provider_name, model_id), memory_gb))
    return matches


def _configured_model_name(config: AppConfig, provider_name: str, provider_model_id: str) -> str | None:
    for model_name, model in config.models.items():
        if str(model.provider or "").strip() == provider_name and str(model.model or "").strip() == provider_model_id:
            return model_name
    return None


def _dedupe_candidates(items: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, object]] = []
    for item in items:
        key = (str(item.get("provider_name") or ""), str(item.get("provider_model_id") or item.get("name") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
