from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import AppConfig, ModelConfig, ProviderConfig, ProviderRuntimeConfig, ProviderDeviceConfig, ProviderHostConfig


DEFAULT_LMSTUDIO_BASES = (
    "http://127.0.0.1:1234",
    "http://localhost:1234",
    "http://host.docker.internal:1234",
)


@dataclass(frozen=True)
class LocalProviderCandidate:
    kind: str
    base_url: str
    openai_base_url: str
    ok: bool
    models: list[dict[str, Any]]
    error: str | None = None
    response_ms: int | None = None
    source: str = "default"

    def model_dump(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "base_url": self.base_url,
            "openai_base_url": self.openai_base_url,
            "ok": self.ok,
            "models": self.models,
            "model_count": len(self.models),
            "error": self.error,
            "response_ms": self.response_ms,
            "source": self.source,
        }


def _normalize_root(url: str) -> str:
    raw = str(url or "").strip().rstrip("/")
    if raw.endswith("/v1"):
        raw = raw[:-3].rstrip("/")
    if raw.endswith("/api/v1"):
        raw = raw[:-7].rstrip("/")
    return raw


def lmstudio_openai_base(url: str) -> str:
    root = _normalize_root(url)
    return f"{root}/v1" if root else ""


def _json_get(url: str, timeout: float) -> tuple[bool, Any, str | None, int]:
    started = time.monotonic()
    req = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode(errors="replace")
            elapsed = int((time.monotonic() - started) * 1000)
            try:
                return True, json.loads(text) if text else {}, None, elapsed
            except json.JSONDecodeError:
                return False, text[:1000], "response was not JSON", elapsed
    except HTTPError as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        return False, exc.read().decode(errors="replace")[:1000], f"HTTP {exc.code}", elapsed
    except URLError as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        return False, {}, str(exc.reason), elapsed
    except Exception as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        return False, {}, str(exc), elapsed


def _models_from_openai_body(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    items = body.get("data") or body.get("models") or []
    models: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            models.append({"id": item, "name": item})
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("name") or item.get("model")
            if model_id:
                models.append({
                    "id": str(model_id),
                    "name": str(item.get("name") or model_id),
                    "object": item.get("object"),
                    "owned_by": item.get("owned_by"),
                    "created": item.get("created"),
                    "raw": item,
                })
    return models


def _safe_provider_name(value: str, existing: set[str]) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "lmstudio").strip()).strip("-._") or "lmstudio"
    if slug not in existing:
        return slug
    i = 2
    while f"{slug}-{i}" in existing:
        i += 1
    return f"{slug}-{i}"


def _candidate_urls(store: Any = None, extra_urls: list[str] | None = None) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []

    def add(url: str, source: str) -> None:
        root = _normalize_root(url)
        if not root or root in seen:
            return
        seen.add(root)
        result.append((root, source))

    for url in DEFAULT_LMSTUDIO_BASES:
        add(url, "default")
    for url in extra_urls or []:
        add(url, "manual")

    if store is not None and hasattr(store, "list_runners"):
        for runner in store.list_runners():
            endpoint = str(getattr(runner, "endpoint", "") or "").strip()
            if not endpoint:
                continue
            try:
                parsed = urllib.parse.urlparse(endpoint if "://" in endpoint else f"http://{endpoint}")
                if parsed.hostname:
                    add(f"http://{parsed.hostname}:1234", f"endpoint:{getattr(runner, 'id', '') or getattr(runner, 'name', '')}")
            except Exception:
                continue
    return result


def discover_lmstudio(store: Any = None, *, extra_urls: list[str] | None = None, timeout_seconds: float = 1.5) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for root, source in _candidate_urls(store, extra_urls):
        openai_base = lmstudio_openai_base(root)
        ok, body, error, response_ms = _json_get(f"{openai_base}/models", timeout=max(0.2, float(timeout_seconds)))
        models = _models_from_openai_body(body) if ok else []
        candidate = LocalProviderCandidate(
            kind="lmstudio",
            base_url=root,
            openai_base_url=openai_base,
            ok=ok,
            models=models,
            error=error,
            response_ms=response_ms,
            source=source,
        )
        candidates.append(candidate.model_dump())
    return {
        "ok": any(item.get("ok") for item in candidates),
        "kind": "lmstudio",
        "candidates": candidates,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def lmstudio_health(base_url: str, *, timeout_seconds: float = 3.0, chat_test: bool = False, model: str | None = None) -> dict[str, Any]:
    root = _normalize_root(base_url)
    openai_base = lmstudio_openai_base(root)
    ok, body, error, response_ms = _json_get(f"{openai_base}/models", timeout=max(0.2, float(timeout_seconds)))
    models = _models_from_openai_body(body) if ok else []
    result: dict[str, Any] = {
        "ok": ok,
        "kind": "lmstudio",
        "base_url": root,
        "openai_base_url": openai_base,
        "models": models,
        "model_count": len(models),
        "error": error,
        "response_ms": response_ms,
        "checks": {"models_endpoint": ok, "has_models": bool(models)},
    }
    if chat_test and models:
        target = model or str(models[0].get("id") or models[0].get("name") or "")
        payload = {"model": target, "messages": [{"role": "user", "content": "Reply with: ok"}], "max_tokens": 4, "temperature": 0, "stream": False}
        started = time.monotonic()
        req = Request(f"{openai_base}/chat/completions", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(req, timeout=max(1.0, float(timeout_seconds))) as resp:
                chat_body = resp.read().decode(errors="replace")[:2000]
            result["checks"]["chat_completion"] = True
            result["chat_response_ms"] = int((time.monotonic() - started) * 1000)
            result["chat_preview"] = chat_body[:300]
        except Exception as exc:
            result["checks"]["chat_completion"] = False
            result["chat_error"] = str(exc)
            result["ok"] = False
    return result


def register_lmstudio_provider(
    config: AppConfig,
    *,
    name: str | None,
    base_url: str,
    enabled: bool = True,
    overwrite: bool = False,
    cached_models: list[dict[str, Any]] | None = None,
) -> tuple[str, ProviderConfig]:
    provider_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(name or "lmstudio").strip()).strip("-._") or "lmstudio"
    if provider_name in config.providers and not overwrite:
        provider_name = _safe_provider_name(provider_name, set(config.providers.keys()))
    provider = ProviderConfig(
        type="lmstudio",
        base_url=lmstudio_openai_base(base_url),
        enabled=bool(enabled),
        status="unknown" if enabled else "disabled",
        timeout_seconds=120,
        cached_models=list(cached_models or []),
        notes="Discovered by PAC local inference discovery.",
        runtime=ProviderRuntimeConfig(
            execution_type="local",
            provider_class="lmstudio",
            device=ProviderDeviceConfig(category="unknown"),
            host=ProviderHostConfig(kind="desktop"),
        ),
    )
    config.providers[provider_name] = provider
    return provider_name, provider


def suggested_model_name(provider_name: str, model_id: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]+", "-", model_id.split("/")[-1] or model_id).strip("-._").lower()
    return f"{provider_name}-{base or 'model'}"


def create_lmstudio_models_from_inventory(config: AppConfig, provider_name: str, models: list[dict[str, Any]], *, limit: int = 12) -> list[str]:
    created: list[str] = []
    for item in models[: max(0, int(limit))]:
        model_id = str(item.get("id") or item.get("name") or "").strip()
        if not model_id:
            continue
        if any(existing.provider == provider_name and existing.model == model_id for existing in config.models.values()):
            continue
        name = _safe_provider_name(suggested_model_name(provider_name, model_id), set(config.models.keys()))
        config.models[name] = ModelConfig(
            display_name=model_id,
            provider=provider_name,
            model=model_id,
            runs_on=None,
            context_window=32768,
            max_output_tokens=4096,
            input_price_per_million=0,
            output_price_per_million=0,
            extra={"local_inference": True, "lmstudio": True},
        )
        created.append(name)
    return created
