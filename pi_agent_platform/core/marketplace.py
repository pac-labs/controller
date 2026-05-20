from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import HTTPException

from pi_agent_platform.core.config import AppConfig
from pi_agent_platform.core.models import Event

HF_API = 'https://huggingface.co/api'
MARKETPLACE_QUANTS = ['q2_k', 'q3_k_m', 'q4_0', 'q4_k_m', 'q5_k_m', 'q6_k', 'q8_0', 'f16', 'f32']


def _hf_headers() -> dict[str, str]:
    headers = {'Accept': 'application/json'}
    token = os.environ.get('HF_TOKEN', '').strip()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def _hf_get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers=_hf_headers())
    try:
        with urllib.request.urlopen(request, timeout=20) as handle:
            return json.loads(handle.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f'Hugging Face API error {exc.code}: {exc.reason}') from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f'Hugging Face API unreachable: {exc.reason or exc}') from exc


def _hf_model_api_url(model_id: str) -> str:
    return f'{HF_API}/models/{urllib.parse.quote(model_id, safe="/")}'


def _marketplace_param_billions(model_id: str) -> float | None:
    match = re.search(r'(\d+(?:\.\d+)?)\s*[bB](?:[^a-zA-Z]|$)', model_id or '')
    return float(match.group(1)) if match else None


def _marketplace_vram_gb(params_b: float | None, quant: str) -> float | None:
    if not params_b:
        return None
    bits = {
        'q8_0': 8,
        'q6_k': 6,
        'q5_k_m': 5,
        'q4_k_m': 4.5,
        'q4_0': 4,
        'q3_k_m': 3.5,
        'q2_k': 2.5,
        'f16': 16,
        'f32': 32,
    }.get(str(quant or '').lower(), 4.5)
    return round(params_b * bits / 8, 2)


def _marketplace_capabilities(model_id: str, tags: list[str]) -> dict[str, bool]:
    text = str(model_id or '').lower()
    tag_set = {str(tag).lower() for tag in (tags or [])}
    return {
        'coding': any(token in text for token in ['coder', 'codellama', 'starcoder', 'deepseek-coder', 'qwen2.5-coder', 'code']),
        'reasoning': any(token in text for token in ['reason', 'r1', 'think']) or 'reasoning' in tag_set,
        'tool_use': any(token in text for token in ['tool', 'function', 'agent']) or 'tool-use' in tag_set,
        'vision': any(token in text for token in ['vision', 'llava', 'vl']) or 'vision' in tag_set,
        'embedding': 'embedding' in text or 'feature-extraction' in tag_set,
        'fast': any(token in text for token in ['0.5b', '1b', '2b', '3b', 'tiny', 'nano']),
        'chat': any(token in tag_set for token in ['conversational', 'text-generation', 'causal-lm']),
    }


def _marketplace_available_quants(siblings: list[dict[str, Any]]) -> list[str]:
    quants: set[str] = set()
    for sibling in siblings or []:
        filename = str(sibling.get('rfilename') or '')
        if not filename.endswith('.gguf'):
            continue
        match = re.search(r'(q\d(?:[_-][a-z0-9]+)+|f16|f32)', filename, re.IGNORECASE)
        if match:
            quants.add(match.group(1).lower().replace('-', '_'))
    return sorted(quants, key=lambda value: MARKETPLACE_QUANTS.index(value) if value in MARKETPLACE_QUANTS else 999)


def marketplace_provider_profiles(config: AppConfig) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for name, provider in sorted((config.providers or {}).items()):
        runtime = provider.runtime
        provider_models = [model_name for model_name, model in (config.models or {}).items() if model.provider == name]
        attached_endpoints = sorted({model.runs_on for model in config.models.values() if model.provider == name and model.runs_on})
        profiles.append(
            {
                'name': name,
                'type': provider.type,
                'enabled': provider.enabled,
                'status': provider.status,
                'base_url': provider.base_url,
                'cached_model_count': len(provider.cached_models or []),
                'execution_type': runtime.execution_type,
                'provider_class': runtime.provider_class,
                'device': runtime.device.model_dump(),
                'host': runtime.host.model_dump(),
                'accelerators': list(runtime.accelerators or []),
                'configured_models': provider_models,
                'attached_endpoints': attached_endpoints,
            }
        )
    return profiles


def _provider_marketplace_fit(params_b: float | None, quants: list[str], profile: dict[str, Any]) -> dict[str, Any]:
    device = profile.get('device') or {}
    memory_gb = device.get('memory_gb')
    candidates = quants or ['q4_k_m']
    if not params_b:
        return {'can_run': None, 'reason': 'Model parameter size could not be inferred', 'quant_recommended': None, 'estimated_vram_gb': None}
    chosen_quant = None
    chosen_vram = None
    if memory_gb:
        for quant in candidates:
            needed = _marketplace_vram_gb(params_b, quant)
            if needed is not None and needed <= float(memory_gb):
                chosen_quant = quant
                chosen_vram = needed
                break
    if not memory_gb:
        fallback = candidates[0] if candidates else 'q4_k_m'
        return {'can_run': None, 'reason': 'Provider memory is not configured yet', 'quant_recommended': fallback.upper(), 'estimated_vram_gb': _marketplace_vram_gb(params_b, fallback)}
    if not chosen_quant:
        smallest = _marketplace_vram_gb(params_b, candidates[0])
        return {'can_run': False, 'reason': f'Needs about {smallest} GB at {candidates[0].upper()}, provider advertises {memory_gb} GB', 'quant_recommended': None, 'estimated_vram_gb': smallest}
    headroom = round(float(memory_gb) - float(chosen_vram or 0), 2)
    return {'can_run': True, 'reason': f'{chosen_quant.upper()} fits with {headroom} GB headroom', 'quant_recommended': chosen_quant.upper(), 'estimated_vram_gb': chosen_vram}


def marketplace_model_detail(config: AppConfig, model_id: str) -> dict[str, Any]:
    try:
        model = _hf_get_json(_hf_model_api_url(model_id))
    except HTTPException:
        query = urllib.parse.quote(str(model_id or ''))
        raw = _hf_get_json(f'{HF_API}/models?search={query}&filter=gguf&full=true&limit=25')
        match = next((item for item in (raw or []) if str(item.get('id') or '').lower() == str(model_id or '').lower()), None)
        if not match:
            raise
        model = match
    siblings = model.get('siblings', []) or []
    tags = [str(tag) for tag in (model.get('tags') or [])]
    quants = _marketplace_available_quants(siblings)
    params_b = _marketplace_param_billions(model.get('id') or model_id)
    providers = [
        {'provider': profile, **_provider_marketplace_fit(params_b, quants, profile)}
        for profile in marketplace_provider_profiles(config)
    ]
    return {
        'model_id': model.get('id') or model_id,
        'author': model.get('author'),
        'downloads': model.get('downloads', 0),
        'likes': model.get('likes', 0),
        'tags': tags,
        'last_modified': model.get('lastModified'),
        'pipeline_tag': model.get('pipeline_tag'),
        'params_b': params_b,
        'capabilities': _marketplace_capabilities(model.get('id') or model_id, tags),
        'available_quants': quants,
        'provider_scores': providers,
        'gated': bool(model.get('gated')),
        'private': bool(model.get('private')),
    }


def marketplace_search_models(config: AppConfig, q: str, limit: int, sort: str, capability: str | None) -> dict[str, Any]:
    provider_profiles = marketplace_provider_profiles(config)
    params = [('search', q), ('filter', 'gguf'), ('full', 'true'), ('direction', '-1'), ('limit', max(1, min(limit, 50))), ('sort', sort)]
    query = '&'.join(f'{key}={urllib.parse.quote(str(value))}' for key, value in params if str(value))
    raw = _hf_get_json(f'{HF_API}/models?{query}')
    results: list[dict[str, Any]] = []
    for item in list(raw or [])[:limit]:
        model_id = str(item.get('id') or '')
        tags = [str(tag) for tag in (item.get('tags') or [])]
        siblings = item.get('siblings') or []
        if not any(str(sibling.get('rfilename') or '').endswith('.gguf') for sibling in siblings):
            try:
                detail = _hf_get_json(_hf_model_api_url(model_id))
                siblings = detail.get('siblings') or []
            except HTTPException:
                siblings = []
        quants = _marketplace_available_quants(siblings)
        if not quants:
            continue
        capabilities = _marketplace_capabilities(model_id, tags)
        if capability and capability not in {'all', 'any'} and not capabilities.get(capability, False):
            continue
        params_b = _marketplace_param_billions(model_id)
        provider_scores = [{'provider': profile, **_provider_marketplace_fit(params_b, quants, profile)} for profile in provider_profiles]
        preferred_fit = (
            next((entry for entry in provider_scores if entry.get('can_run') is True), None)
            or next((entry for entry in provider_scores if entry.get('provider', {}).get('type') == 'lmstudio'), None)
            or (provider_scores[0] if provider_scores else None)
        )
        results.append(
            {
                'model_id': model_id,
                'author': item.get('author'),
                'downloads': item.get('downloads', 0),
                'likes': item.get('likes', 0),
                'tags': tags,
                'last_modified': item.get('lastModified'),
                'capabilities': capabilities,
                'params_b': params_b,
                'available_quants': quants,
                'vram_q4_k_m_gb': _marketplace_vram_gb(params_b, 'q4_k_m'),
                'provider_scores': provider_scores,
                'preferred_fit': preferred_fit,
                'gated': bool(item.get('gated')),
                'private': bool(item.get('private')),
            }
        )
    return {'query': q, 'results': results, 'total': len(results)}


def marketplace_download_model(config: AppConfig, store: Any, model: str, provider_name: str, quantization: str | None) -> dict[str, Any]:
    provider = config.providers.get(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail='Provider not found')
    if provider.type != 'lmstudio' or not provider.base_url:
        raise HTTPException(status_code=400, detail='Marketplace download is currently supported only for configured LM Studio providers')
    base = provider.base_url.rstrip('/')
    if base.endswith('/v1'):
        base = base[:-3]
    request_body = json.dumps({'model': f'https://huggingface.co/{model}', 'quantization': quantization or 'Q4_K_M'}).encode('utf-8')
    request = urllib.request.Request(
        f'{base}/api/v1/models/download',
        data=request_body,
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as handle:
            result = json.loads(handle.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='ignore')
        raise HTTPException(status_code=502, detail=f'LM Studio download failed ({exc.code}): {body}') from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f'LM Studio provider unreachable: {exc.reason or exc}') from exc
    store.add_event(
        Event(
            session_id='system',
            type='marketplace_download_started',
            message=f'Marketplace download requested: {model} via {provider_name}',
            data={'model': model, 'provider': provider_name, 'quantization': quantization or 'Q4_K_M', 'result': result},
        )
    )
    return result
