from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen
import json

from .config import AppConfig, ModelConfig, ProviderConfig, ContextProfile


def _provider_for_model(config: AppConfig, model_name: str) -> tuple[ModelConfig, ProviderConfig | None]:
    model = config.models[model_name]
    provider = config.providers.get(model.provider)
    return model, provider


def effective_context(config: AppConfig, model_name: str, context_profile_name: str | None = None) -> dict[str, Any]:
    model, _provider = _provider_for_model(config, model_name)
    profile: ContextProfile | None = None
    if context_profile_name:
        profile = config.context_profiles.get(context_profile_name)
    if not profile:
        profile = config.context_profiles.get("medium") or ContextProfile()
    effective = min(model.context_window, profile.budget_tokens)
    output = min(model.max_output_tokens, profile.reserve_output_tokens, effective)
    return {
        "model_context_window": model.context_window,
        "profile_budget_tokens": profile.budget_tokens,
        "effective_context_tokens": effective,
        "reserve_output_tokens": output,
        "history_tokens": min(profile.history_tokens, max(0, effective - output)),
        "file_context_tokens": min(profile.file_context_tokens, max(0, effective - output)),
        "summarization": profile.summarization,
    }


def provider_public(config: AppConfig) -> dict[str, Any]:
    return {
        name: p.model_dump(exclude={"api_key"})
        for name, p in config.providers.items()
    }


def model_card(config: AppConfig, model_name: str) -> dict[str, Any]:
    model, provider = _provider_for_model(config, model_name)
    return {
        "name": model_name,
        "model": model.model_dump(),
        "provider": provider.model_dump(exclude={"api_key"}) if provider else None,
        "effective_context_medium": effective_context(config, model_name, "medium"),
    }


def _provider_api_key(provider: ProviderConfig) -> str | None:
    return provider.api_key or (os.environ.get(provider.api_key_env) if provider.api_key_env else None)


def _json_request(url: str, provider: ProviderConfig, payload: dict[str, Any] | None = None) -> tuple[bool, Any]:
    headers = {"Content-Type": "application/json", **provider.default_headers}
    api_key = _provider_api_key(provider)
    if api_key and provider.type in {"anthropic", "anthropic-compatible", "minimax"}:
        headers.setdefault("x-api-key", api_key)
        headers.setdefault("anthropic-version", "2023-06-01")
    elif api_key and provider.type == "gemini":
        pass
    elif api_key:
        headers.setdefault("Authorization", f"Bearer {api_key}")
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with urlopen(req, timeout=provider.timeout_seconds) as resp:
            body = resp.read().decode(errors="replace")
            try:
                return True, json.loads(body) if body else {}
            except json.JSONDecodeError:
                return True, body[:1000]
    except HTTPError as exc:
        return False, {"error": f"HTTP {exc.code}", "body": exc.read().decode(errors="replace")[:1000]}
    except URLError as exc:
        return False, {"error": str(exc.reason)}
    except Exception as exc:
        return False, {"error": str(exc)}



def _stream_openai_chat(url: str, provider: ProviderConfig, payload: dict[str, Any]) -> tuple[bool, Any]:
    """Read OpenAI-compatible SSE chat streams.

    For LM Studio this avoids a single hard request timeout while the model is
    still producing tokens. urllib's timeout is an inactivity timeout, so active
    token streaming keeps the request alive and still fails if the server stalls.
    """
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream", **provider.default_headers}
    api_key = _provider_api_key(provider)
    if api_key:
        headers.setdefault("Authorization", f"Bearer {api_key}")
    req = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    chunks: list[str] = []
    try:
        with urlopen(req, timeout=max(30, provider.timeout_seconds)) as resp:
            for raw in resp:
                line = raw.decode(errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    item = json.loads(data)
                    delta = item.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        chunks.append(content)
                except Exception:
                    continue
        return True, "".join(chunks)
    except HTTPError as exc:
        return False, {"error": f"HTTP {exc.code}", "body": exc.read().decode(errors="replace")[:1000]}
    except URLError as exc:
        return False, {"error": str(exc.reason)}
    except Exception as exc:
        return False, {"error": str(exc)}


def normalize_provider_base_url(provider: ProviderConfig, model: ModelConfig | None = None) -> str:
    """Return the API base URL PAC should use for model/provider calls.

    LM Studio, vLLM and most OpenAI-compatible servers expose OpenAI-style
    routes below /v1. Users often paste the host root from LM Studio
    (http://host:1234), so PAC normalizes LM Studio/vLLM roots to /v1.
    """
    base = ((model.endpoint if model and model.endpoint else None) or provider.base_url or '').strip().rstrip('/')
    if provider.type in {'openai', 'openai-codex'} and not base:
        base = 'https://api.openai.com/v1'
    if provider.type == 'anthropic' and not base:
        base = 'https://api.anthropic.com/v1'
    if provider.type == 'minimax' and not base:
        base = 'https://api.minimax.io/anthropic/v1'
    if provider.type == 'gemini' and not base:
        base = 'https://generativelanguage.googleapis.com/v1beta'
    if provider.type == 'groq' and not base:
        base = 'https://api.groq.com/openai/v1'
    if provider.type == 'openrouter' and not base:
        base = 'https://openrouter.ai/api/v1'
    if provider.type == 'deepseek' and not base:
        base = 'https://api.deepseek.com/v1'
    if provider.type == 'mistral' and not base:
        base = 'https://api.mistral.ai/v1'
    if provider.type in {'lmstudio', 'vllm'} and base and not base.endswith('/v1'):
        base = base + '/v1'
    if provider.type in {'anthropic-compatible', 'minimax'} and base and not base.endswith('/v1'):
        base = base + '/v1'
    return base


def _parse_model_list(provider_type: str, body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    if provider_type == 'ollama':
        items = body.get('models') or []
        return [
            {
                'id': item.get('name') or item.get('model') or str(item),
                'name': item.get('name') or item.get('model') or str(item),
                'modified_at': item.get('modified_at'),
                'size': item.get('size'),
                'details': item.get('details') or {},
            }
            for item in items if isinstance(item, dict)
        ]
    if provider_type == 'gemini':
        items = body.get('models') or []
        return [
            {
                'id': (item.get('name') or '').replace('models/', '') or str(item),
                'name': (item.get('displayName') or item.get('name') or str(item)),
                'raw': item,
            }
            for item in items if isinstance(item, dict)
        ]
    items = body.get('data') or body.get('models') or []
    result = []
    for item in items:
        if isinstance(item, str):
            result.append({'id': item, 'name': item})
        elif isinstance(item, dict):
            model_id = item.get('id') or item.get('name') or item.get('model')
            if model_id:
                result.append({
                    'id': model_id,
                    'name': model_id,
                    'object': item.get('object'),
                    'owned_by': item.get('owned_by'),
                    'created': item.get('created'),
                    'raw': item,
                })
    return result




def normalize_lmstudio_management_url(provider: ProviderConfig) -> str:
    """Return LM Studio native management API root.

    The OpenAI-compatible server usually lives under /v1, while load/unload/
    download actions are under /api/v1. Users may paste either root.
    """
    base = (provider.base_url or 'http://localhost:1234').strip().rstrip('/')
    if base.endswith('/v1'):
        base = base[:-3].rstrip('/')
    if base.endswith('/api/v1'):
        return base
    return base + '/api/v1'


def lmstudio_native_request(provider: ProviderConfig, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if provider.type != 'lmstudio':
        return {'ok': False, 'error': 'provider is not LM Studio'}
    base = normalize_lmstudio_management_url(provider)
    action = action.strip('/')
    endpoint = f'{base}/{action}'
    ok, body = _json_request(endpoint, provider, payload)
    return {'ok': ok, 'endpoint': endpoint, 'response': body, **({'error': body.get('error')} if isinstance(body, dict) and body.get('error') and not ok else {})}


def lmstudio_load_model(provider: ProviderConfig, model: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {'model': model}
    for key in ('context_length', 'flash_attention', 'echo_load_config', 'eval_batch_size', 'offload_kv_cache_to_gpu', 'num_experts', 'gpu_offload', 'temperature', 'top_p', 'seed', 'rope_frequency_base') :
        if options and key in options and options[key] is not None:
            payload[key] = options[key]
    payload.setdefault('echo_load_config', True)
    return lmstudio_native_request(provider, 'models/load', payload)


def lmstudio_unload_model(provider: ProviderConfig, instance_id: str) -> dict[str, Any]:
    return lmstudio_native_request(provider, 'models/unload', {'instance_id': instance_id})


def lmstudio_download_model(provider: ProviderConfig, model: str) -> dict[str, Any]:
    return lmstudio_native_request(provider, 'models/download', {'model': model})


def lmstudio_inspect_provider(provider: ProviderConfig) -> dict[str, Any]:
    if provider.type != 'lmstudio':
        return {'ok': False, 'error': 'provider is not LM Studio'}
    openai_base = normalize_provider_base_url(provider)
    native_base = normalize_lmstudio_management_url(provider)
    models_ok, models_body = _json_request(f'{openai_base}/models', provider) if openai_base else (False, {'error': 'missing base_url'})
    return {
        'ok': models_ok,
        'type': 'lmstudio',
        'openai_base_url': openai_base,
        'management_base_url': native_base,
        'models': _parse_model_list('lmstudio', models_body),
        'models_response': models_body,
        'notes': 'Host hardware should be reported by the PAC endpoint or the generated companion script; LM Studio model APIs do not guarantee full CPU/GPU inventory.',
    }


def lmstudio_companion_script(provider_name: str, provider: ProviderConfig, report_url: str) -> str:
    base = normalize_lmstudio_management_url(provider).replace('/api/v1','')
    token_env = provider.api_key_env or 'LM_API_TOKEN'
    return f"""#!/usr/bin/env python3
import json, os, platform, socket, subprocess, urllib.request

BASE = {base!r}
REPORT_URL = {report_url!r}
TOKEN_ENV = {token_env!r}
PROVIDER = {provider_name!r}

def get_json(url):
    req = urllib.request.Request(url, headers={{'Authorization': 'Bearer ' + os.environ.get(TOKEN_ENV, '')}} if os.environ.get(TOKEN_ENV) else {{}})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return {{'ok': True, 'body': json.loads(r.read().decode() or '{{}}')}}
    except Exception as e:
        return {{'ok': False, 'error': str(e)}}

def cmd(args):
    try:
        return subprocess.check_output(args, stderr=subprocess.STDOUT, text=True, timeout=8).strip()
    except Exception as e:
        return str(e)

report = {{
    'provider': PROVIDER,
    'host': socket.gethostname(),
    'platform': platform.platform(),
    'hardware': {{
        'processor': platform.processor(),
        'machine': platform.machine(),
        'nvidia_smi': cmd(['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader'])
    }},
    'lmstudio': {{
        'models': get_json(BASE.rstrip('/') + '/v1/models'),
        'native_models': get_json(BASE.rstrip('/') + '/api/v1/models')
    }}
}}
print(json.dumps(report, indent=2))
if REPORT_URL:
    data = json.dumps(report).encode()
    req = urllib.request.Request(REPORT_URL, data=data, headers={{'Content-Type':'application/json'}}, method='POST')
    with urllib.request.urlopen(req, timeout=20) as r:
        print(r.read().decode())
"""
def safe_model_config_name(provider_name: str, model_id: str) -> str:
    """Return a stable PAC config key for a provider model id."""
    raw = f"{provider_name}-{model_id}".strip().lower()
    safe = re.sub(r"[^a-z0-9_.-]+", "-", raw).strip("-._")
    return safe or f"{provider_name}-model"


def sync_models_from_provider(config: AppConfig, provider_name: str, models: list[dict[str, Any]]) -> list[str]:
    """Create/update PAC ModelConfig entries from a live provider model list.

    This converts provider discovery into real selectable PAC models so sessions
    cannot depend on stale/example model names. Existing user-edited entries are
    preserved unless they point at the same provider+model id.
    """
    created_or_updated: list[str] = []
    config.models = config.models or {}
    for item in models or []:
        model_id = item.get('id') or item.get('name') or item.get('model') if isinstance(item, dict) else str(item)
        if not model_id:
            continue
        key = safe_model_config_name(provider_name, str(model_id))
        existing = config.models.get(key)
        if existing:
            existing.provider = provider_name
            existing.model = str(model_id)
        else:
            config.models[key] = ModelConfig(
                provider=provider_name,
                model=str(model_id),
                runs_on=provider_name,
                context_window=32768,
                max_output_tokens=4096,
            )
        created_or_updated.append(key)
    return created_or_updated

def list_provider_models(config: AppConfig, provider_name: str, force: bool = False) -> dict[str, Any]:
    if provider_name not in config.providers:
        return {'ok': False, 'error': 'unknown provider', 'models': []}
    provider = config.providers[provider_name]
    if not force and getattr(provider, 'enabled', True) is False:
        return {
            'ok': False,
            'type': provider.type,
            'status': 'disabled',
            'error': 'provider is disabled',
            'models': getattr(provider, 'cached_models', []) or [],
        }
    if provider.type in {'openai', 'openai-codex', 'openai-compatible', 'lmstudio', 'vllm', 'groq', 'openrouter', 'deepseek', 'mistral'}:
        base = normalize_provider_base_url(provider)
        if not base:
            return {'ok': False, 'error': 'provider has no base_url', 'models': []}
        ok, body = _json_request(f'{base}/models', provider)
        models = _parse_model_list(provider.type, body)
        return {'ok': ok, 'type': provider.type, 'endpoint': f'{base}/models', 'models': models, 'response': body}
    if provider.type in {'anthropic', 'anthropic-compatible', 'minimax'}:
        base = normalize_provider_base_url(provider)
        if not base:
            return {'ok': False, 'error': 'provider has no base_url', 'models': []}
        ok, body = _json_request(f'{base}/models', provider)
        models = _parse_model_list(provider.type, body)
        return {'ok': ok, 'type': provider.type, 'endpoint': f'{base}/models', 'models': models, 'response': body}
    if provider.type == 'gemini':
        base = normalize_provider_base_url(provider)
        api_key = _provider_api_key(provider)
        suffix = f'?key={api_key}' if api_key else ''
        ok, body = _json_request(f'{base}/models{suffix}', provider)
        models = _parse_model_list(provider.type, body)
        return {'ok': ok, 'type': provider.type, 'endpoint': f'{base}/models', 'models': models, 'response': body}
    if provider.type == 'ollama':
        base = (provider.base_url or 'http://localhost:11434').rstrip('/')
        ok, body = _json_request(f'{base}/api/tags', provider)
        models = _parse_model_list(provider.type, body)
        return {'ok': ok, 'type': provider.type, 'endpoint': f'{base}/api/tags', 'models': models, 'response': body}
    return {'ok': False, 'type': provider.type, 'error': 'model listing is not implemented for this provider type', 'models': []}

def test_provider(config: AppConfig, provider_name: str) -> dict[str, Any]:
    if provider_name not in config.providers:
        return {"ok": False, "error": "unknown provider"}
    provider = config.providers[provider_name]
    result = list_provider_models(config, provider_name, force=True)
    return {
        "ok": result.get("ok", False),
        "type": provider.type,
        "endpoint": result.get("endpoint"),
        "models": result.get("models", []),
        "response": result.get("response", result),
        "error": result.get("error"),
    }

def test_model(config: AppConfig, model_name: str) -> dict[str, Any]:
    if model_name not in config.models:
        return {"ok": False, "error": "unknown model"}
    model, provider = _provider_for_model(config, model_name)
    if not provider:
        return {"ok": False, "error": f"unknown provider: {model.provider}"}
    if provider.type in {"openai", "openai-codex", "openai-compatible", "lmstudio", "vllm", "groq", "openrouter", "deepseek", "mistral"}:
        base = normalize_provider_base_url(provider, model)
        payload = {
            "model": model.model or model_name,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "max_tokens": min(16, model.max_output_tokens),
            "stream": False,
        }
        ok, body = _json_request(f"{base}/chat/completions", provider, payload)
        return {"ok": ok, "type": provider.type, "endpoint": f"{base}/chat/completions", "model": payload["model"], "response": body}
    if provider.type in {"anthropic", "anthropic-compatible", "minimax"}:
        base = normalize_provider_base_url(provider, model)
        payload = {"model": model.model or model_name, "messages": [{"role": "user", "content": "Reply with OK."}], "max_tokens": min(16, model.max_output_tokens)}
        ok, body = _json_request(f"{base}/messages", provider, payload)
        return {"ok": ok, "type": provider.type, "endpoint": f"{base}/messages", "model": payload["model"], "response": body}
    if provider.type == "gemini":
        base = normalize_provider_base_url(provider, model)
        api_key = _provider_api_key(provider)
        suffix = f"?key={api_key}" if api_key else ""
        model_id = model.model or model_name
        payload = {"contents": [{"parts": [{"text": "Reply with OK."}]}], "generationConfig": {"maxOutputTokens": min(16, model.max_output_tokens)}}
        ok, body = _json_request(f"{base}/models/{model_id}:generateContent{suffix}", provider, payload)
        return {"ok": ok, "type": provider.type, "endpoint": f"{base}/models/{model_id}:generateContent", "model": model_id, "response": body}
    if provider.type == "ollama":
        base = (model.endpoint or provider.base_url or "http://localhost:11434").rstrip("/")
        payload = {"model": model.model or model_name, "prompt": "Reply with OK.", "stream": False}
        ok, body = _json_request(f"{base}/api/generate", provider, payload)
        return {"ok": ok, "type": provider.type, "endpoint": f"{base}/api/generate", "model": payload["model"], "response": body}
    return {"ok": False, "type": provider.type, "error": "model test placeholder for this provider type"}


def sync_model_context(config: AppConfig, model_name: str) -> dict[str, Any]:
    """Query the provider's /v1/models for actual context_length and update model config."""
    if model_name not in config.models:
        return {"ok": False, "error": "unknown model"}
    model, provider = _provider_for_model(config, model_name)
    if not provider:
        return {"ok": False, "error": f"unknown provider: {model.provider}"}
    if not provider.enabled:
        return {"ok": False, "error": "provider is not enabled", "model": model_name}
    base = normalize_provider_base_url(provider, model)
    if not base:
        return {"ok": False, "error": "provider has no base_url", "model": model_name}
    ok, body = _json_request(f"{base}/models", provider)
    if not ok:
        return {"ok": False, "error": f"unreachable: {body.get('error', body)}", "model": model_name}
    models = _parse_model_list(provider.type, body)
    model_id = model.model or model_name
    found = next((m for m in models if m.get("id") == model_id or m.get("name") == model_id), None)
    if not found:
        return {"ok": False, "error": f"model {model_id} not in provider list", "model": model_name, "provider_models": [m.get("id") for m in models]}
    raw = found.get("raw") or {}
    context_length = raw.get("context_length") or raw.get("max_model_len")
    suggested_context = int(context_length) if context_length else None
    suggested_output = int(context_length // 4) if context_length else None
    return {
        "ok": True,
        "model": model_name,
        "provider": model.provider,
        "stored": {"context_window": model.context_window, "max_output_tokens": model.max_output_tokens},
        "provider_info": {"context_length": context_length, "max_model_len": raw.get("max_model_len")},
        "suggested": {"context_window": suggested_context, "max_output_tokens": suggested_output},
        "mismatch": {
            "context_window": suggested_context is not None and suggested_context != model.context_window,
            "max_output_tokens": suggested_output is not None and suggested_output != model.max_output_tokens,
        },
    }


def update_model_limits(config: AppConfig, model_name: str, context_window: int | None = None, max_output_tokens: int | None = None) -> dict[str, Any]:
    """Update context_window and/or max_output_tokens for a model."""
    if model_name not in config.models:
        return {"ok": False, "error": "unknown model"}
    model = config.models[model_name]
    if context_window is not None:
        model.context_window = context_window
    if max_output_tokens is not None:
        model.max_output_tokens = max_output_tokens
    return {"ok": True, "model": model_name, "context_window": model.context_window, "max_output_tokens": model.max_output_tokens}



def chat_complete(config: AppConfig, model_name: str, messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
    """Small synchronous chat abstraction for Stage 8 agent loop.

    Supports OpenAI-compatible providers including LM Studio and vLLM, plus Ollama.
    """
    if model_name not in config.models:
        raise ValueError(f"unknown model: {model_name}")
    model, provider = _provider_for_model(config, model_name)
    if not provider:
        raise ValueError(f"unknown provider: {model.provider}")
    max_tokens = max_tokens or model.max_output_tokens
    if provider.type in {"openai", "openai-codex", "openai-compatible", "lmstudio", "vllm", "groq", "openrouter", "deepseek", "mistral"}:
        base = normalize_provider_base_url(provider, model)
        if not base:
            raise ValueError("provider has no base_url")
        payload = {
            "model": model.model or model_name,
            "messages": messages,
            "max_tokens": min(max_tokens, model.max_output_tokens),
            "temperature": model.extra.get("temperature", 0.2),
            "stream": provider.type == "lmstudio",
        }
        if provider.type == "lmstudio":
            ok, body = _stream_openai_chat(f"{base}/chat/completions", provider, payload)
        else:
            ok, body = _json_request(f"{base}/chat/completions", provider, payload)
        if not ok:
            raise RuntimeError(body)
        if isinstance(body, str):
            return body
        try:
            return body["choices"][0]["message"]["content"] or ""
        except Exception:
            raise RuntimeError(f"unexpected chat response: {body}")
    if provider.type == "ollama":
        base = (model.endpoint or provider.base_url or "http://localhost:11434").rstrip("/")
        prompt = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages) + "\nASSISTANT:"
        payload = {"model": model.model or model_name, "prompt": prompt, "stream": False, "options": {"num_predict": min(max_tokens, model.max_output_tokens)}}
        ok, body = _json_request(f"{base}/api/generate", provider, payload)
        if not ok:
            raise RuntimeError(body)
        return body.get("response", "")
    raise ValueError(f"provider type not supported for chat_complete: {provider.type}")
