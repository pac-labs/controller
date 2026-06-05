from __future__ import annotations

from typing import Any

from .config import AppConfig
from .llmfit import llmfit_recommendations, llmfit_status
from .marketplace import marketplace_model_detail, marketplace_provider_profiles

CURATED_PUBLIC_CODING_MODELS = [
    "mistralai/Devstral-Small-2507_gguf",
    "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
    "Qwen/Qwen2.5-Coder-32B-Instruct-GGUF",
    "Qwen/Qwen3-Coder-Next-GGUF",
]


def coding_improvement_advice(config: AppConfig) -> dict[str, Any]:
    configured = _configured_coding_models(config)
    llmfit = llmfit_recommendations(
        use_case="coding",
        limit=4,
        max_context=_max_context(config),
        timeout_seconds=4.0,
    )
    local_candidates = _local_provider_candidates(config, configured)
    public_candidates = _public_marketplace_candidates(config, configured)
    current_best = max((float(item.get("score") or 0.0) for item in configured), default=0.0)
    better_local = [item for item in local_candidates if float(item.get("score") or 0.0) > current_best + 6]
    better_public = [item for item in public_candidates if float(item.get("score") or 0.0) > current_best + 6]
    warning = _warning(configured, better_local, better_public, llmfit)
    return {
        "ok": True,
        "llmfit": llmfit,
        "llmfit_status": llmfit_status(timeout_seconds=4.0),
        "configured_models": configured,
        "local_candidates": better_local[:4],
        "public_candidates": better_public[:4],
        "warning": warning,
        "providers": marketplace_provider_profiles(config),
    }


def coding_session_advisory(config: AppConfig, configured_model_name: str) -> dict[str, Any] | None:
    configured = _configured_coding_models(config)
    current = next((item for item in configured if str(item.get("name") or "") == str(configured_model_name or "")), None)
    if not current:
        return None
    llmfit = llmfit_recommendations(
        use_case="coding",
        limit=4,
        max_context=_max_context(config),
        timeout_seconds=4.0,
    )
    local_candidates = _local_provider_candidates(config, configured)
    public_candidates = _public_marketplace_candidates(config, configured)
    current_score = float(current.get("score") or 0.0)
    better_local = [item for item in local_candidates if float(item.get("score") or 0.0) > current_score + 6][:2]
    better_public = [item for item in public_candidates if float(item.get("score") or 0.0) > current_score + 6][:2]
    if float(current.get("score") or 0.0) >= 18 or (not better_local and not better_public):
        return None
    source = "llmfit" if llmfit.get("ok") else "heuristics"
    suggestions: list[str] = []
    for item in better_local:
        provider = str(item.get("provider_name") or "").strip()
        model_id = str(item.get("model_id") or "").strip()
        if provider and model_id:
            suggestions.append(f"Local: {model_id} on {provider}")
    for item in better_public:
        provider = str(item.get("provider_name") or "").strip()
        model_id = str(item.get("model_id") or "").strip()
        if provider and model_id:
            suggestions.append(f"Download: {model_id} to {provider}")
    if not suggestions:
        return None
    message = (
        f"The current coding model `{current.get('name')}` looks weak for this kind of work. "
        f"PAC found better-fit options from {source}: " + "; ".join(suggestions[:3]) +
        ". Should PAC switch or download one of these and reconfigure this session?"
    )
    return {
        "message": message,
        "current_model": current,
        "local_candidates": better_local,
        "public_candidates": better_public,
        "llmfit": llmfit,
        "source": source,
    }


def _configured_coding_models(config: AppConfig) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for name, model in (config.models or {}).items():
        provider = config.providers.get(model.provider)
        provider_name = model.provider
        provider_type = str(getattr(provider, "type", "") or "")
        model_id = str(model.model or name)
        lowered = model_id.lower()
        if "embed" in lowered:
            continue
        function = str((model.extra or {}).get("function") or "")
        score = _coding_score(model_id, function=function, memory_gb=_provider_memory_gb(provider))
        items.append(
            {
                "name": name,
                "provider_name": provider_name,
                "provider_type": provider_type,
                "model_id": model_id,
                "context_window": int(model.context_window or 0),
                "score": score,
                "quality": _score_quality(score),
                "reason": _score_reason(model_id, function=function),
            }
        )
    return sorted(items, key=lambda item: float(item.get("score") or 0.0), reverse=True)


def _local_provider_candidates(config: AppConfig, configured: list[dict[str, Any]]) -> list[dict[str, Any]]:
    configured_refs = {
        (str(item.get("provider_name") or "").strip(), str(item.get("model_id") or "").strip())
        for item in configured
    }
    candidates: list[dict[str, Any]] = []
    for provider_name, provider in (config.providers or {}).items():
        if str(getattr(provider, "type", "") or "").lower() != "lmstudio" or getattr(provider, "enabled", True) is False:
            continue
        memory_gb = _provider_memory_gb(provider)
        for item in getattr(provider, "cached_models", []) or []:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or item.get("name") or item.get("model") or "").strip()
            if not model_id or "embed" in model_id.lower():
                continue
            if (provider_name, model_id) in configured_refs:
                continue
            score = _coding_score(model_id, memory_gb=memory_gb)
            if score <= 0:
                continue
            candidates.append(
                {
                    "provider_name": provider_name,
                    "model_id": model_id,
                    "score": score,
                    "quality": _score_quality(score),
                    "memory_gb": memory_gb,
                    "configured": False,
                    "source": "provider_inventory",
                }
            )
    return sorted(candidates, key=lambda item: float(item.get("score") or 0.0), reverse=True)


def _public_marketplace_candidates(config: AppConfig, configured: list[dict[str, Any]]) -> list[dict[str, Any]]:
    configured_ids = {str(item.get("model_id") or "").strip().lower() for item in configured}
    items: list[dict[str, Any]] = []
    for model_id in CURATED_PUBLIC_CODING_MODELS:
        if model_id.lower() in configured_ids:
            continue
        try:
            detail = marketplace_model_detail(config, model_id)
        except Exception:
            continue
        preferred = _preferred_marketplace_fit(detail)
        provider = preferred.get("provider") if isinstance(preferred, dict) else {}
        can_run = preferred.get("can_run") if isinstance(preferred, dict) else None
        provider_name = str((provider or {}).get("name") or "").strip()
        score = _coding_score(model_id, memory_gb=_provider_profile_memory_gb(provider if isinstance(provider, dict) else None))
        if can_run is False:
            score -= 8.0
        items.append(
            {
                "model_id": detail.get("model_id") or model_id,
                "author": detail.get("author"),
                "params_b": detail.get("params_b"),
                "score": score,
                "quality": _score_quality(score),
                "provider_name": provider_name,
                "can_run": can_run,
                "quantization": preferred.get("quant_recommended") if isinstance(preferred, dict) else None,
                "fit_reason": preferred.get("reason") if isinstance(preferred, dict) else None,
                "downloadable": True,
                "source": "huggingface_marketplace",
            }
        )
    return sorted(items, key=lambda item: float(item.get("score") or 0.0), reverse=True)


def _preferred_marketplace_fit(detail: dict[str, Any]) -> dict[str, Any]:
    preferred = detail.get("preferred_fit")
    if isinstance(preferred, dict) and preferred.get("provider"):
        return preferred
    provider_scores = detail.get("provider_scores") if isinstance(detail.get("provider_scores"), list) else []
    lmstudio_scores = [item for item in provider_scores if isinstance(item, dict) and isinstance(item.get("provider"), dict) and item["provider"].get("type") == "lmstudio"]
    if not lmstudio_scores:
        return {}
    runnable = next((item for item in lmstudio_scores if item.get("can_run") is True), None)
    if runnable:
        return runnable
    return max(
        lmstudio_scores,
        key=lambda item: float(((item.get("provider") or {}).get("device") or {}).get("memory_gb") or 0.0),
        default={},
    )


def _warning(
    configured: list[dict[str, Any]],
    local_candidates: list[dict[str, Any]],
    public_candidates: list[dict[str, Any]],
    llmfit: dict[str, Any],
) -> dict[str, Any]:
    current_best = configured[0] if configured else None
    if not current_best:
        return {
            "level": "warn",
            "title": "No coding-focused model is configured",
            "summary": "PAC has no strong coding model configured yet. Add one from provider inventory or the public marketplace.",
        }
    weak = float(current_best.get("score") or 0.0) < 18
    if weak and (local_candidates or public_candidates):
        source = "llmfit" if llmfit.get("ok") else "heuristics"
        return {
            "level": "warn",
            "title": f"{current_best.get('name')} looks weak for coding work",
            "summary": f"PAC can see better-fit options from {source}. Consider switching before relying on this model for code changes.",
        }
    if local_candidates or public_candidates:
        return {
            "level": "info",
            "title": "Stronger coding models are available",
            "summary": "PAC found additional local or public models that may be a better fit for coding-heavy sessions.",
        }
    return {
        "level": "ok",
        "title": "Current coding model coverage looks reasonable",
        "summary": "PAC does not currently see a clearly better local or public coding model for the configured providers.",
    }


def _coding_score(model_id: str, *, function: str = "", memory_gb: float | None = None) -> float:
    lowered = str(model_id or "").lower()
    score = 0.0
    if any(token in lowered for token in ["devstral", "coder", "deepseek-coder", "code"]):
        score += 18.0
    if "qwen" in lowered:
        score += 10.0
    if "reason" in lowered:
        score += 4.0
    if function.lower() in {"coding", "programming", "reviewer"}:
        score += 5.0
    if "32b" in lowered or "33b" in lowered or "30b" in lowered:
        score += 14.0
    elif "24b" in lowered or "27b" in lowered:
        score += 12.0
    elif "14b" in lowered or "12b" in lowered:
        score += 7.0
    elif "7b" in lowered or "8b" in lowered:
        score += 3.0
    elif "4b" in lowered or "3b" in lowered:
        score -= 4.0
    if any(token in lowered for token in ["tiny", "nano", "flash", "e4b"]):
        score -= 8.0
    if memory_gb and memory_gb >= 20:
        score += 6.0
    elif memory_gb and memory_gb < 10:
        score -= 2.0
    return score


def _score_reason(model_id: str, *, function: str = "") -> str:
    lowered = str(model_id or "").lower()
    reasons: list[str] = []
    if "devstral" in lowered:
        reasons.append("agentic coding tuned")
    if "coder" in lowered or "deepseek-coder" in lowered:
        reasons.append("code-specific training")
    if "qwen" in lowered:
        reasons.append("strong open coding family")
    if any(token in lowered for token in ["tiny", "nano", "flash", "e4b"]):
        reasons.append("small or latency-optimized variant")
    if function:
        reasons.append(f"configured for {function}")
    return ", ".join(reasons) or "generic chat model"


def _score_quality(score: float) -> str:
    if score >= 28:
        return "strong"
    if score >= 18:
        return "usable"
    return "weak"


def _provider_memory_gb(provider: Any) -> float | None:
    runtime = getattr(provider, "runtime", None)
    device = getattr(runtime, "device", None) if runtime else None
    try:
        value = getattr(device, "memory_gb", None)
        return float(value) if value is not None else None
    except Exception:
        return None


def _provider_profile_memory_gb(profile: dict[str, Any] | None) -> float | None:
    if not isinstance(profile, dict):
        return None
    device = profile.get("device") if isinstance(profile.get("device"), dict) else {}
    try:
        value = device.get("memory_gb")
        return float(value) if value is not None else None
    except Exception:
        return None


def _max_context(config: AppConfig) -> int | None:
    try:
        return max(int(item.context_window or 0) for item in (config.models or {}).values()) or None
    except Exception:
        return None
