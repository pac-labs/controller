from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from pi_agent_platform.core.config import ProviderConfig
from pi_agent_platform.core.directory_identities import ensure_provider_principal, retire_provider_principal
from pi_agent_platform.core.models import Event
from pi_agent_platform.core.observability import log_file_map, read_log_tail
from pi_agent_platform.core.local_inference import (
    create_lmstudio_models_from_inventory,
    discover_lmstudio,
    lmstudio_health,
    register_lmstudio_provider,
)


def create_providers_router(
    *,
    require_auth: Any,
    get_config: Any,
    save_config: Any,
    store: Any,
    model_available: Any,
    provider_public: Any,
    list_provider_models: Any,
    sync_models_from_provider: Any,
    test_provider: Any,
    lmstudio_inspect_provider: Any,
    lmstudio_companion_script: Any,
    lmstudio_load_model: Any,
    lmstudio_unload_model: Any,
    lmstudio_download_model: Any,
    model_card: Any,
    test_model: Any,
    effective_context: Any,
    list_artifacts: Any,
    write_artifact: Any,
    task_artifact_dir: Any,
    safe_artifact_path: Any,
    ensure_controller_harness_session: Any,
    pacp_path: Any,
    wrapper_process_state: Any,
    pi_dev_daemon_state: Any,
    bootstrap_active: Any,
    start_controller_bootstrap: Any,
    ensure_controller_wrapper: Any,
    restart_controller_wrapper: Any,
    refresh_local_runner_metadata: Any,
    require_resource_access: Any,
) -> APIRouter:
    """Provider, model, profile, tool catalog, and artifact routes.

    This module keeps the configuration-backed model/provider surface out of
    the controller bootstrap while preserving the current config ownership
    model. A later service-layer pass can replace these injected callables with
    explicit provider/profile/artifact services.
    """
    router = APIRouter()

    _get_config = get_config
    _model_available = model_available
    _ensure_controller_harness_session = ensure_controller_harness_session
    _pacp_path = pacp_path
    _wrapper_process_state = wrapper_process_state
    _pi_dev_daemon_state = pi_dev_daemon_state
    _bootstrap_active = bootstrap_active
    _start_controller_bootstrap = start_controller_bootstrap
    _ensure_controller_wrapper = ensure_controller_wrapper
    _restart_controller_wrapper = restart_controller_wrapper
    _refresh_local_runner_metadata = refresh_local_runner_metadata



    @router.get('/v1/local-inference/lmstudio/discover')
    def local_lmstudio_discover(timeout_seconds: float = 1.5, url: str | None = None, _auth: Any = Depends(require_auth)) -> dict:
        require_resource_access(_auth, 'provider', '*', 'read')
        extra_urls = [url] if url else []
        result = discover_lmstudio(store, extra_urls=extra_urls, timeout_seconds=timeout_seconds)
        store.add_event(Event(session_id='system', type='local_provider_discovery', message='LM Studio discovery completed', data={'kind': 'lmstudio', 'ok': result.get('ok'), 'candidates': len(result.get('candidates') or [])}))
        return result


    @router.post('/v1/local-inference/lmstudio/health')
    def local_lmstudio_health(payload: dict[str, Any], _auth: Any = Depends(require_auth)) -> dict:
        require_resource_access(_auth, 'provider', '*', 'read')
        base_url = str(payload.get('base_url') or payload.get('url') or '').strip()
        if not base_url:
            raise HTTPException(status_code=400, detail='base_url is required')
        result = lmstudio_health(
            base_url,
            timeout_seconds=float(payload.get('timeout_seconds') or 3.0),
            chat_test=bool(payload.get('chat_test', False)),
            model=payload.get('model'),
        )
        store.add_event(Event(session_id='system', type='local_provider_health', message=f'LM Studio health: {"ok" if result.get("ok") else "failed"}', data={'kind': 'lmstudio', 'base_url': base_url, 'ok': result.get('ok'), 'models': result.get('model_count')}))
        return result


    @router.post('/v1/local-inference/lmstudio/register')
    def local_lmstudio_register(payload: dict[str, Any], _auth: Any = Depends(require_auth)) -> dict:
        require_resource_access(_auth, 'provider', '*', 'manage')
        config = _get_config()
        base_url = str(payload.get('base_url') or payload.get('url') or '').strip()
        if not base_url:
            raise HTTPException(status_code=400, detail='base_url is required')
        health = lmstudio_health(base_url, timeout_seconds=float(payload.get('timeout_seconds') or 3.0), chat_test=bool(payload.get('chat_test', False)))
        if not health.get('ok') and not bool(payload.get('force', False)):
            raise HTTPException(status_code=400, detail={'message': 'LM Studio server is not healthy. Pass force=true to register anyway.', 'health': health})
        provider_name, provider = register_lmstudio_provider(
            config,
            name=payload.get('name'),
            base_url=base_url,
            enabled=bool(payload.get('enabled', True)),
            overwrite=bool(payload.get('overwrite', False)),
            cached_models=health.get('models') or [],
        )
        created_models: list[str] = []
        if bool(payload.get('create_models', True)):
            created_models = create_lmstudio_models_from_inventory(config, provider_name, health.get('models') or [], limit=int(payload.get('model_limit') or 12))
        save_config(config)
        ensure_provider_principal(store, provider_name, provider)
        store.add_event(Event(session_id='system', type='local_provider_registered', message=f'LM Studio provider registered: {provider_name}', data={'provider': provider_name, 'base_url': provider.base_url, 'models': len(provider.cached_models), 'created_models': created_models}))
        return {'ok': True, 'provider': provider_name, 'registered': provider.model_dump(mode='json', exclude={'api_key'}), 'health': health, 'created_models': created_models}

    @router.get('/v1/models')
    def list_models(_auth: Any = Depends(require_auth)) -> dict:
        require_resource_access(_auth, 'model', '*', 'read')
        config = _get_config()
        result = {}
        for name, model in config.models.items():
            data = model.model_dump()
            available, reason = _model_available(name)
            data['available'] = available
            data['availability_reason'] = reason
            result[name] = data
        return result


    @router.get('/v1/providers')
    def list_providers(_auth: Any = Depends(require_auth)) -> dict:
        require_resource_access(_auth, 'provider', '*', 'read')
        config = _get_config()
        return provider_public(config)


    @router.get('/v1/providers/{provider_name}/models')
    def provider_models(provider_name: str, _auth: Any = Depends(require_auth)) -> dict:
        require_resource_access(_auth, 'provider', provider_name, 'read')
        config = _get_config()
        return list_provider_models(config, provider_name)


    @router.post('/v1/providers/{provider_name}/toggle')
    def provider_toggle(provider_name: str, payload: dict[str, Any], _auth: Any = Depends(require_auth)) -> dict:
        require_resource_access(_auth, 'provider', provider_name, 'manage')
        config = _get_config()
        if provider_name not in config.providers:
            raise HTTPException(status_code=404, detail='Provider not found')
        enabled = bool(payload.get('enabled'))
        provider = config.providers[provider_name]
        provider.enabled = enabled
        provider.last_checked_at = datetime.now(timezone.utc).isoformat()
        if not enabled:
            provider.status = 'disabled'
            provider.last_error = None
            save_config(config)
            ensure_provider_principal(store, provider_name, provider)
            store.add_event(Event(session_id='system', type='provider_disabled', message=f'Provider disabled: {provider_name}'))
            return {'ok': True, 'enabled': False, 'status': provider.status, 'models': provider.cached_models}
        result = list_provider_models(config, provider_name, force=True)
        provider.cached_models = result.get('models', []) or []
        synced_models = sync_models_from_provider(config, provider_name, provider.cached_models) if result.get('ok') else []
        provider.status = 'connected' if result.get('ok') else 'failed'
        provider.last_error = None if result.get('ok') else (result.get('error') or result.get('response', {}).get('error') if isinstance(result.get('response'), dict) else 'connection failed')
        save_config(config)
        ensure_provider_principal(store, provider_name, provider)
        store.add_event(Event(session_id='system', type='provider_connected' if result.get('ok') else 'provider_failed', message=f'Provider {provider_name}: {provider.status}', data={'provider': provider_name, 'status': provider.status, 'models': len(provider.cached_models), 'synced_models': synced_models}))
        return {'ok': result.get('ok', False), 'enabled': True, 'status': provider.status, 'last_error': provider.last_error, 'endpoint': result.get('endpoint'), 'models': provider.cached_models, 'synced_models': synced_models, 'response': result.get('response')}


    @router.put('/v1/providers/{provider_name}')
    def provider_update(provider_name: str, payload: dict[str, Any], _auth: Any = Depends(require_auth)) -> dict:
        require_resource_access(_auth, 'provider', provider_name, 'manage')
        config = _get_config()
        existing = config.providers.get(provider_name)
        data = dict(payload)
        if existing:
            merged = existing.model_dump(mode='json', exclude_none=True)
            merged.update(data)
            data = merged
        config.providers[provider_name] = ProviderConfig.model_validate(data)
        save_config(config)
        ensure_provider_principal(store, provider_name, config.providers[provider_name])
        store.add_event(Event(session_id='system', type='provider_updated', message=f'Provider updated: {provider_name}'))
        return provider_public(config)[provider_name]


    @router.delete('/v1/providers/{provider_name}')
    def provider_delete(provider_name: str, _auth: Any = Depends(require_auth)) -> dict:
        require_resource_access(_auth, 'provider', provider_name, 'manage')
        config = _get_config()
        if provider_name not in config.providers:
            raise HTTPException(status_code=404, detail='Provider not found')
        del config.providers[provider_name]
        retire_provider_principal(store, provider_name)
        removed_models = [name for name, model in list(config.models.items()) if model.provider == provider_name]
        for name in removed_models:
            del config.models[name]
        save_config(config)
        store.add_event(Event(session_id='system', type='provider_deleted', message=f'Provider deleted: {provider_name}', data={'removed_models': removed_models}))
        return {'ok': True, 'deleted': provider_name, 'removed_models': removed_models}


    @router.post('/v1/providers/{provider_name}/test')
    def provider_health(provider_name: str, _auth: Any = Depends(require_auth)) -> dict:
        require_resource_access(_auth, 'provider', provider_name, 'read')
        config = _get_config()
        return test_provider(config, provider_name)



    @router.get('/v1/providers/{provider_name}/lmstudio/inspect')
    def provider_lmstudio_inspect(provider_name: str, _auth: None = Depends(require_auth)) -> dict:
        config = _get_config()
        provider = config.providers.get(provider_name)
        if not provider:
            raise HTTPException(status_code=404, detail='Provider not found')
        result = lmstudio_inspect_provider(provider)
        store.add_event(Event(session_id='system', type='lmstudio_inspected', message=f'LM Studio inspected: {provider_name}', data={'provider': provider_name, 'ok': result.get('ok'), 'models': len(result.get('models') or [])}))
        return result


    @router.get('/v1/providers/{provider_name}/lmstudio/companion-script')
    def provider_lmstudio_companion_script(provider_name: str, _auth: None = Depends(require_auth)) -> dict:
        config = _get_config()
        provider = config.providers.get(provider_name)
        if not provider:
            raise HTTPException(status_code=404, detail='Provider not found')
        public = (config.server.public_url or '').rstrip('/')
        report_url = f'{public}/v1/providers/{provider_name}/lmstudio/companion-report' if public else ''
        return {'ok': True, 'provider': provider_name, 'script': lmstudio_companion_script(provider_name, provider, report_url), 'report_url': report_url}


    @router.post('/v1/providers/{provider_name}/lmstudio/companion-report')
    def provider_lmstudio_companion_report(provider_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict:
        config = _get_config()
        provider = config.providers.get(provider_name)
        if not provider:
            raise HTTPException(status_code=404, detail='Provider not found')
        extra = provider.default_headers.setdefault('x-pac-companion-report', 'available')
        provider.notes = ((provider.notes or '') + '\nLM Studio companion report received.').strip()
        provider.last_checked_at = datetime.now(timezone.utc).isoformat()
        provider.cached_models = payload.get('lmstudio', {}).get('models', {}).get('body', {}).get('data', provider.cached_models) if isinstance(payload, dict) else provider.cached_models
        save_config(config)
        store.add_event(Event(session_id='system', type='lmstudio_companion_reported', message=f'LM Studio companion reported hardware: {provider_name}', data={'provider': provider_name, 'host': payload.get('host'), 'hardware': payload.get('hardware')}))
        return {'ok': True, 'provider': provider_name, 'message': 'report received'}


    @router.post('/v1/providers/{provider_name}/lmstudio/load')
    def provider_lmstudio_load(provider_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict:
        config = _get_config()
        provider = config.providers.get(provider_name)
        if not provider:
            raise HTTPException(status_code=404, detail='Provider not found')
        model = str(payload.get('model') or '').strip()
        if not model:
            raise HTTPException(status_code=400, detail='model is required')
        result = lmstudio_load_model(provider, model, payload)
        store.add_event(Event(session_id='system', type='lmstudio_model_load', message=f'LM Studio load {model}: {"ok" if result.get("ok") else "failed"}', data={'provider': provider_name, 'model': model, 'result': result}))
        return result


    @router.post('/v1/providers/{provider_name}/lmstudio/unload')
    def provider_lmstudio_unload(provider_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict:
        config = _get_config()
        provider = config.providers.get(provider_name)
        if not provider:
            raise HTTPException(status_code=404, detail='Provider not found')
        instance_id = str(payload.get('instance_id') or payload.get('model') or '').strip()
        if not instance_id:
            raise HTTPException(status_code=400, detail='instance_id is required')
        result = lmstudio_unload_model(provider, instance_id)
        store.add_event(Event(session_id='system', type='lmstudio_model_unload', message=f'LM Studio unload {instance_id}: {"ok" if result.get("ok") else "failed"}', data={'provider': provider_name, 'instance_id': instance_id, 'result': result}))
        return result


    @router.post('/v1/providers/{provider_name}/lmstudio/download')
    def provider_lmstudio_download(provider_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict:
        config = _get_config()
        provider = config.providers.get(provider_name)
        if not provider:
            raise HTTPException(status_code=404, detail='Provider not found')
        model = str(payload.get('model') or '').strip()
        if not model:
            raise HTTPException(status_code=400, detail='model is required')
        result = lmstudio_download_model(provider, model)
        store.add_event(Event(session_id='system', type='lmstudio_model_download', message=f'LM Studio download {model}: {"queued" if result.get("ok") else "failed"}', data={'provider': provider_name, 'model': model, 'result': result}))
        return result


    @router.get('/v1/models/{model_name}/card')
    def get_model_card(model_name: str, context_profile: str | None = None, _auth: Any = Depends(require_auth)) -> dict:
        require_resource_access(_auth, 'model', model_name, 'read')
        config = _get_config()
        if model_name not in config.models:
            raise HTTPException(status_code=404, detail='Model not found')
        card = model_card(config, model_name)
        if context_profile:
            card['effective_context'] = effective_context(config, model_name, context_profile)
        return card


    @router.post('/v1/models/{model_name}/test')
    def model_health(model_name: str, _auth: None = Depends(require_auth)) -> dict:
        config = _get_config()
        return test_model(config, model_name)


    @router.get('/v1/models/provider-status')
    def model_provider_status(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'provider', '*', 'read')
        config = _get_config()
        from pi_agent_platform.core.providers import sync_model_context
        results = []
        for name in config.models:
            result = sync_model_context(config, name)
            if result.get('ok') is False and 'error' in result:
                results.append({
                    'name': name,
                    'error': result.get('error'),
                    'provider': config.models[name].provider,
                    'stored': {'context_window': config.models[name].context_window, 'max_output_tokens': config.models[name].max_output_tokens},
                    'provider_info': {},
                    'mismatch': {'context_window': False, 'max_output_tokens': False},
                    'suggested': {},
                })
            else:
                results.append(result)
        return {'models': results}


    @router.patch('/v1/models/{model_name}')
    def model_update_limits(model_name: str, payload: dict[str, Any], _auth: Any = Depends(require_auth)) -> dict:
        require_resource_access(_auth, 'model', model_name, 'manage')
        config = _get_config()
        if model_name not in config.models:
            raise HTTPException(status_code=404, detail='Model not found')
        from pi_agent_platform.core.providers import update_model_limits
        result = update_model_limits(config, model_name,
            context_window=payload.get('context_window'),
            max_output_tokens=payload.get('max_output_tokens'))
        if result.get('ok'):
            save_config(config)
            store.add_event(Event(session_id='system', type='model_limits_updated', message=f'Model limits updated: {model_name}', data={'model': model_name, 'context_window': result.get('context_window'), 'max_output_tokens': result.get('max_output_tokens')}))
        return result


    @router.get('/v1/models/{model_name}/lmstudio/inspect')
    def model_lmstudio_inspect(model_name: str, _auth: None = Depends(require_auth)) -> dict:
        config = _get_config()
        if model_name not in config.models:
            raise HTTPException(status_code=404, detail='Model not found')
        model = config.models[model_name]
        provider = config.providers.get(model.provider)
        if not provider or provider.type != 'lmstudio':
            raise HTTPException(status_code=400, detail='Model is not backed by an LM Studio provider')
        result = lmstudio_inspect_provider(provider)
        result['model_name'] = model_name
        result['provider_model_id'] = model.model
        result['saved_runtime'] = (model.extra or {}).get('lmstudio_runtime', {})
        store.add_event(Event(session_id='system', type='lmstudio_model_view_inspected', message=f'LM Studio model inspected: {model_name}', data={'model': model_name, 'provider': model.provider, 'ok': result.get('ok')}))
        return result


    @router.post('/v1/models/{model_name}/lmstudio/load')
    def model_lmstudio_load(model_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict:
        config = _get_config()
        if model_name not in config.models:
            raise HTTPException(status_code=404, detail='Model not found')
        model = config.models[model_name]
        provider = config.providers.get(model.provider)
        if not provider or provider.type != 'lmstudio':
            raise HTTPException(status_code=400, detail='Model is not backed by an LM Studio provider')
        runtime = dict((model.extra or {}).get('lmstudio_runtime', {}))
        runtime.update({k: v for k, v in payload.items() if v is not None and k != 'model'})
        target_model = str(payload.get('model') or model.model or model_name).strip()
        if not target_model:
            raise HTTPException(status_code=400, detail='provider model id is required')
        result = lmstudio_load_model(provider, target_model, runtime)
        store.add_event(Event(session_id='system', type='lmstudio_model_view_load', message=f'LM Studio load from model view {model_name}: {"ok" if result.get("ok") else "failed"}', data={'model': model_name, 'provider': model.provider, 'provider_model': target_model, 'runtime': runtime, 'result': result}))
        return result


    @router.post('/v1/models/{model_name}/lmstudio/unload')
    def model_lmstudio_unload(model_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict:
        config = _get_config()
        if model_name not in config.models:
            raise HTTPException(status_code=404, detail='Model not found')
        model = config.models[model_name]
        provider = config.providers.get(model.provider)
        if not provider or provider.type != 'lmstudio':
            raise HTTPException(status_code=400, detail='Model is not backed by an LM Studio provider')
        instance_id = str(payload.get('instance_id') or payload.get('model') or model.model or model_name).strip()
        if not instance_id:
            raise HTTPException(status_code=400, detail='instance_id is required')
        result = lmstudio_unload_model(provider, instance_id)
        store.add_event(Event(session_id='system', type='lmstudio_model_view_unload', message=f'LM Studio unload from model view {model_name}: {"ok" if result.get("ok") else "failed"}', data={'model': model_name, 'provider': model.provider, 'instance_id': instance_id, 'result': result}))
        return result


    @router.get('/v1/context-profiles')
    def list_context_profiles(_auth: None = Depends(require_auth)) -> dict:
        config = _get_config()
        return {name: cp.model_dump() for name, cp in config.context_profiles.items()}


    @router.get('/v1/models/{model_name}/effective-context')
    def get_effective_context(model_name: str, context_profile: str = 'medium', _auth: None = Depends(require_auth)) -> dict:
        config = _get_config()
        if model_name not in config.models:
            raise HTTPException(status_code=404, detail='Model not found')
        return effective_context(config, model_name, context_profile)


    @router.get('/v1/tool-packages')
    def list_tool_packages(_auth: None = Depends(require_auth)) -> dict:
        config = _get_config()
        return {name: package.model_dump() for name, package in config.tool_packages.items()}

    @router.get('/v1/plugins')
    def list_plugins(_auth: None = Depends(require_auth)) -> dict:
        config = _get_config()
        return {name: plugin.model_dump() for name, plugin in config.plugins.items()}

    @router.get('/v1/tools')
    def list_tools(_auth: None = Depends(require_auth)) -> dict:
        config = _get_config()
        return {name: tool.model_dump() for name, tool in config.tools.items()}


    @router.get('/v1/artifacts')
    def api_list_artifacts(session_id: str | None = None, task_id: str | None = None, _auth: None = Depends(require_auth)) -> list[dict[str, Any]]:
        config = _get_config()
        return list_artifacts(config.server.data_dir, session_id, task_id)


    @router.put('/v1/artifacts/{session_id}/{task_id}/{name:path}')
    async def api_put_artifact(session_id: str, task_id: str, name: str, request: Request, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        config = _get_config()
        data = await request.body()
        task_id_norm = None if task_id == 'session' else task_id
        meta = write_artifact(config.server.data_dir, session_id, task_id_norm, name, data)
        store.add_event(Event(session_id=session_id, task_id=task_id_norm, type='artifact_uploaded', message=f'Uploaded artifact {name}', data=meta))
        return meta


    @router.get('/v1/artifacts/{session_id}/{task_id}/{name:path}')
    def api_get_artifact(session_id: str, task_id: str, name: str, _auth: None = Depends(require_auth)):
        config = _get_config()
        task_id_norm = None if task_id == 'session' else task_id
        base = task_artifact_dir(config.server.data_dir, session_id, task_id_norm)
        try:
            target = safe_artifact_path(base, name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not target.exists() or target.name.endswith('.meta.json'):
            raise HTTPException(status_code=404, detail='Artifact not found')
        return FileResponse(target, filename=Path(name).name)





    @router.get('/v1/controller-harness')
    def controller_harness_status(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'system', 'controller-harness', 'read')
        return _ensure_controller_harness_session()


    @router.get('/v1/controller-harness/diagnostics')
    def controller_harness_diagnostics(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', 'controller-harness', 'read')
        status = _ensure_controller_harness_session()
        logs = log_file_map()
        wrapper_log = logs["wrapper"]
        pi_agent_log = logs["pi-agent"]
        pacctl_log = logs["pacctl"]
        wrapper_tail = read_log_tail(wrapper_log, limit=12000).get("content", "")
        pi_agent_tail = read_log_tail(pi_agent_log, limit=12000).get("content", "")
        pacctl_tail = read_log_tail(pacctl_log, limit=12000).get("content", "")
        return {
            'status': status,
            'wrapper_process': _wrapper_process_state(),
            'pi_daemon': _pi_dev_daemon_state(),
            'wrapper_log': str(wrapper_log),
            'wrapper_log_tail': wrapper_tail,
            'pi_agent_log': str(pi_agent_log),
            'pi_agent_log_tail': pi_agent_tail,
            'pacctl_log': str(pacctl_log),
            'pacctl_log_tail': pacctl_tail,
        }


    @router.post('/v1/controller-harness/bootstrap')
    def bootstrap_controller_harness(_auth: None = Depends(require_auth)) -> dict[str, Any]:
        if _bootstrap_active():
            return {'status': 'running', 'message': 'Controller pi.dev bootstrap is already running. Progress is shown in Events.'}
        started = _start_controller_bootstrap(force=True)
        return {'status': 'running' if started else 'disabled', 'message': 'Controller pi.dev bootstrap started. Progress is shown in Events.' if started else 'Controller pi.dev is disabled in Settings.'}


    @router.post('/v1/controller-harness/update-wrapper')
    def update_controller_wrapper(_auth: None = Depends(require_auth)) -> dict[str, Any]:
        config = _get_config()
        wrapper_result = _ensure_controller_wrapper(allow_build=True, force_rebuild=True)
        restart_result = _restart_controller_wrapper() if wrapper_result.get('ok') else {'ok': False, 'status': 'skipped', 'message': 'Wrapper restart skipped because build/install did not succeed.'}
        refreshed = _refresh_local_runner_metadata(emit_event=False)
        payload = {
            'ok': bool(wrapper_result.get('ok')) and bool(restart_result.get('ok')),
            'wrapper': wrapper_result,
            'restart': restart_result,
            'runner': refreshed.model_dump(),
            'diagnostics': {
                'wrapper_process': _wrapper_process_state(),
                'pi_daemon': _pi_dev_daemon_state(),
            },
            'message': 'Controller wrapper updated and restarted.' if wrapper_result.get('ok') and restart_result.get('ok') else (wrapper_result.get('message') or restart_result.get('message') or 'Controller wrapper update needs attention.'),
        }
        store.add_event(Event(session_id='system', type='controller_wrapper_updated' if payload['ok'] else 'controller_wrapper_update_failed', message=payload['message'], data=payload))
        return payload


    @router.post('/v1/controller-harness/settings')
    def save_controller_harness_settings(payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict[str, Any]:
        config = _get_config()
        current = config.controller_harness.model_dump()
        allowed = set(current.keys())
        merged = {**current, **{k: v for k, v in payload.items() if k in allowed}}
        if merged.get('agent_profile') in ('', 'none'):
            merged['agent_profile'] = None
        if merged.get('model') in ('', 'profile'):
            merged['model'] = None
        if merged.get('workspace_profile') not in config.workspaces:
            # It is valid to name a new workspace here; the harness will create it.
            pass
        if merged.get('agent_profile') and merged['agent_profile'] not in config.agent_profiles:
            raise HTTPException(status_code=400, detail=f"Unknown agent profile: {merged['agent_profile']}")
        if merged.get('model') and merged['model'] not in config.models:
            raise HTTPException(status_code=400, detail=f"Unknown model: {merged['model']}")
        if merged.get('permission_profile') and merged['permission_profile'] not in config.permission_profiles:
            raise HTTPException(status_code=400, detail=f"Unknown permission profile: {merged['permission_profile']}")
        config.controller_harness = type(config.controller_harness).model_validate(merged)
        save_config(config)
        config = _get_config()
        result = _ensure_controller_harness_session()
        store.add_event(Event(session_id='system', type='controller_harness_settings_saved', message='Controller pi.dev settings saved', data={'ok': result.get('ok'), 'message': result.get('message')}))
        return result


    @router.delete('/v1/models/{model_name}')
    def delete_model(model_name: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'model', model_name, 'manage')
        config = _get_config()
        if model_name not in config.models:
            raise HTTPException(status_code=404, detail='Model not found')
        if getattr(config.models[model_name], 'read_only', False):
            raise HTTPException(status_code=403, detail=f'Model {model_name} is read-only and cannot be deleted')
        del config.models[model_name]
        save_config(config)
        store.add_event(Event(session_id='system', type='model_deleted', message=f'Model deleted: {model_name}', data={'model': model_name}))
        return {'ok': True, 'deleted': model_name}


    return router
