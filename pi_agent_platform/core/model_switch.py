from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import AppConfig, ModelConfig
from .models import Event, Session, Task
from .store import store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class ModelSwitchCandidate:
    name: str
    model: ModelConfig
    score: int = 0
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ModelSwitchResult:
    ok: bool
    selected_model: str = ""
    previous_model: str = ""
    requested: str = ""
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    fallback_chain: list[str] = field(default_factory=list)
    capability_report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "selected_model": self.selected_model,
            "previous_model": self.previous_model,
            "requested": self.requested,
            "reason": self.reason,
            "warnings": self.warnings,
            "fallback_chain": self.fallback_chain,
            "capability_report": self.capability_report,
        }


def model_display_name(name: str, model: ModelConfig) -> str:
    label = model.display_name or name
    provider_model = model.model or name
    if provider_model and provider_model != name:
        return f"{label} ({provider_model})"
    return label


def list_model_switch_options(config: AppConfig) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for name, model in sorted(config.models.items()):
        provider = config.providers.get(model.provider)
        caps = model.capabilities
        options.append({
            "name": name,
            "display_name": model_display_name(name, model),
            "provider": model.provider,
            "provider_type": provider.type if provider else "missing",
            "provider_status": provider.status if provider else "missing",
            "enabled": bool(provider and provider.enabled and provider.status not in {"disabled", "failed"}),
            "model": model.model or name,
            "context_window": model.context_window,
            "supports_chat": bool(getattr(caps, "supports_chat", True)),
            "supports_tools": bool(getattr(caps, "supports_tools", False)),
            "supports_json": bool(getattr(caps, "supports_json", False)),
            "supports_streaming": bool(getattr(caps, "supports_streaming", True)),
            "reasoning": getattr(caps, "reasoning", "none"),
        })
    return options


def _normalize(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "-").replace("_", "-")


def _provider_model_match(config: AppConfig, provider_name: str, wanted: str) -> str:
    wanted_norm = _normalize(wanted)
    for name, model in config.models.items():
        if model.provider != provider_name:
            continue
        values = {name, model.model or "", model.display_name or ""}
        if wanted_norm in {_normalize(item) for item in values if item}:
            return name
    return ""


def resolve_model_selector(config: AppConfig, selector: str) -> tuple[str, str]:
    raw = str(selector or "").strip()
    if not raw:
        return "", "empty selector"
    if raw in config.models:
        return raw, "exact model id"
    raw_norm = _normalize(raw)
    for name, model in config.models.items():
        if raw_norm in {_normalize(name), _normalize(model.display_name or ""), _normalize(model.model or "")}:
            return name, "model alias"
    if ":" in raw:
        provider_part, model_part = raw.split(":", 1)
        provider_norm = _normalize(provider_part)
        matching_providers = [
            name for name, provider in config.providers.items()
            if _normalize(name) == provider_norm or _normalize(provider.type) == provider_norm
        ]
        for provider_name in matching_providers:
            match = _provider_model_match(config, provider_name, model_part)
            if match:
                return match, f"provider-qualified model selector ({provider_name})"
    if "/" in raw:
        provider_part, model_part = raw.split("/", 1)
        if provider_part in config.providers:
            match = _provider_model_match(config, provider_part, model_part)
            if match:
                return match, f"provider/model selector ({provider_part})"
    return "", f"model selector did not match a configured model: {raw}"


def model_capability_report(config: AppConfig, model_name: str, session: Session | None = None) -> dict[str, Any]:
    model = config.models.get(model_name)
    if not model:
        return {"ok": False, "reason": "model is not configured"}
    provider = config.providers.get(model.provider)
    caps = model.capabilities
    warnings: list[str] = []
    if not provider:
        return {"ok": False, "reason": f"provider is not configured: {model.provider}"}
    if provider.enabled is False or provider.status in {"disabled", "failed"}:
        return {"ok": False, "reason": f"provider is not connected: {model.provider} ({provider.status})"}
    if getattr(caps, "supports_chat", True) is False:
        return {"ok": False, "reason": "model does not support chat"}
    cached = getattr(provider, "cached_models", []) or []
    if cached:
        wanted = model.model or model_name
        ids = {str(item.get("id") or item.get("name") or item.get("model")) for item in cached if isinstance(item, dict)}
        if str(wanted) not in ids:
            warnings.append(f"Provider inventory does not list {wanted}; switching is allowed but the next call may fail.")
    agent_like = bool(session and ((session.metadata or {}).get("agent_enabled") or (session.tools or [])))
    if agent_like and not getattr(caps, "supports_json", False):
        warnings.append("Model is not marked JSON-capable; structured agent decisions may be weaker.")
    if agent_like and not getattr(caps, "supports_tools", False):
        warnings.append("Model is not marked tool-capable; PAC may need a structured fallback decision model.")
    return {
        "ok": True,
        "provider": model.provider,
        "provider_type": provider.type,
        "provider_status": provider.status,
        "model": model.model or model_name,
        "context_window": model.context_window,
        "max_output_tokens": model.max_output_tokens,
        "supports_chat": bool(getattr(caps, "supports_chat", True)),
        "supports_tools": bool(getattr(caps, "supports_tools", False)),
        "supports_json": bool(getattr(caps, "supports_json", False)),
        "supports_vision": bool(getattr(caps, "supports_vision", False)),
        "supports_streaming": bool(getattr(caps, "supports_streaming", True)),
        "reasoning": getattr(caps, "reasoning", "none"),
        "warnings": warnings,
    }


def _score_model(model: ModelConfig) -> int:
    caps = model.capabilities
    return (
        (4 if getattr(caps, "supports_tools", False) else 0)
        + (3 if getattr(caps, "supports_json", False) else 0)
        + {"none": 0, "low": 1, "medium": 2, "high": 3}.get(str(getattr(caps, "reasoning", "none") or "none"), 0)
        + min(int(model.context_window or 0) // 32000, 6)
    )


def build_fallback_chain(config: AppConfig, primary: str, explicit: list[str] | None = None, limit: int = 4) -> list[str]:
    chain: list[str] = []
    for selector in explicit or []:
        resolved, _reason = resolve_model_selector(config, selector)
        if resolved and resolved != primary and resolved not in chain:
            report = model_capability_report(config, resolved)
            if report.get("ok"):
                chain.append(resolved)
    ranked: list[tuple[int, str]] = []
    for name, model in config.models.items():
        if name == primary or name in chain:
            continue
        report = model_capability_report(config, name)
        if not report.get("ok"):
            continue
        ranked.append((_score_model(model), name))
    ranked.sort(reverse=True)
    for _score, name in ranked:
        if len(chain) >= limit:
            break
        chain.append(name)
    return chain[:limit]


def switch_session_model(
    config: AppConfig,
    session: Session,
    selector: str,
    *,
    task: Task | None = None,
    role: str = "session",
    fallback_selectors: list[str] | None = None,
    source: str = "slash_command",
) -> ModelSwitchResult:
    selected, reason = resolve_model_selector(config, selector)
    previous = session.model
    if not selected:
        result = ModelSwitchResult(ok=False, previous_model=previous, requested=selector, reason=reason)
        _emit_model_switch_event(session, task, result, source=source, role=role)
        return result
    report = model_capability_report(config, selected, session)
    if not report.get("ok"):
        result = ModelSwitchResult(ok=False, selected_model=selected, previous_model=previous, requested=selector, reason=str(report.get("reason") or "model unavailable"), capability_report=report)
        _emit_model_switch_event(session, task, result, source=source, role=role)
        return result
    fallback_chain = build_fallback_chain(config, selected, explicit=fallback_selectors)
    session.model = selected
    session.metadata = dict(session.metadata or {})
    session.metadata["active_model"] = selected
    session.metadata["active_model_role"] = role
    session.metadata["model_fallback_chain"] = fallback_chain
    history = list(session.metadata.get("model_history") or [])
    history.append({
        "at": _now(),
        "from": previous,
        "to": selected,
        "requested": selector,
        "role": role,
        "source": source,
        "reason": reason,
        "fallback_chain": fallback_chain,
    })
    session.metadata["model_history"] = history[-30:]
    session.touch()
    store.add_session(session)
    if task is not None:
        task.metadata["model"] = selected
        task.metadata["model_switched_to"] = selected
        task.metadata["model_fallback_chain"] = fallback_chain
        store.add_task(task)
    result = ModelSwitchResult(
        ok=True,
        selected_model=selected,
        previous_model=previous,
        requested=selector,
        reason=reason,
        warnings=list(report.get("warnings") or []),
        fallback_chain=fallback_chain,
        capability_report=report,
    )
    _emit_model_switch_event(session, task, result, source=source, role=role)
    return result


def _emit_model_switch_event(session: Session, task: Task | None, result: ModelSwitchResult, *, source: str, role: str) -> None:
    if result.ok:
        title = "Model switched"
        summary = f"Session model changed from {result.previous_model or '-'} to {result.selected_model}."
        message = summary
    else:
        title = "Model switch failed"
        summary = result.reason
        message = f"Model switch failed: {result.reason}"
    data = {
        **result.to_dict(),
        "source": source,
        "role": role,
        "timeline": {
            "title": title,
            "summary": summary,
            "fields": {
                "Requested": result.requested or "-",
                "Previous": result.previous_model or "-",
                "Selected": result.selected_model or "-",
                "Fallbacks": ", ".join(result.fallback_chain) if result.fallback_chain else "-",
            },
        },
    }
    store.add_event(Event(session_id=session.id, task_id=task.id if task else None, type="model_switched" if result.ok else "model_switch_failed", message=message, data=data))


def model_options_text(config: AppConfig, session: Session | None = None) -> str:
    rows = []
    current = session.model if session else ""
    for item in list_model_switch_options(config):
        marker = "*" if item["name"] == current else " "
        enabled = "ok" if item["enabled"] else "unavailable"
        caps = []
        if item.get("supports_tools"):
            caps.append("tools")
        if item.get("supports_json"):
            caps.append("json")
        if item.get("reasoning") and item.get("reasoning") != "none":
            caps.append(f"reasoning:{item['reasoning']}")
        rows.append(f"{marker} {item['name']} [{item['provider']}:{item['provider_type']}, {enabled}] {'/'.join(caps) or 'chat'}")
    return "Available models:\n" + "\n".join(rows)
