from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pi_agent_platform.core.config import AppConfig
from pi_agent_platform.core.models import Event


class EndpointCertificateRequest(BaseModel):
    name: str
    csr_pem: str | None = None
    sans: list[str] = []
    days: int | None = None


class ServiceModeRequest(BaseModel):
    mode: str


class LetsEncryptEnableRequest(BaseModel):
    email: str
    domain: str
    cloudflare_api_token: str
    cloudflare_zone_id: str
    auto_enable: bool = True
    staging: bool = False


def create_service_runtime_router(
    *,
    require_auth: Callable[..., Any],
    get_config: Callable[[], AppConfig],
    save_config: Callable[[AppConfig], None],
    store: Any,
    service_status_payload: Callable[[], dict[str, Any]],
    write_system_service_unit: Callable[[str, int], tuple[Path, Path]],
    write_user_service_unit: Callable[[str, int], Path],
    run_quiet: Callable[..., dict[str, Any]],
    can_sudo_noninteractive: Callable[[], bool],
    user_service_port: Callable[[], int],
    preserve_or_default_public_url: Callable[[str | None, int], str],
    schedule_local_restart: Callable[[BackgroundTasks, str], None],
    ensure_tls_material: Callable[[], dict[str, Any]],
    mdns_config: Callable[[], dict[str, Any]],
    mdns_status: Callable[[], dict[str, Any]],
    issue_endpoint_certificate: Callable[[str, str | None, list[str], int | None], dict[str, Any]],
    get_letsencrypt_status: Callable[[], dict[str, Any]],
    check_domain_dns: Callable[[str], dict[str, Any]],
    test_cloudflare_credentials: Callable[[str, str], dict[str, Any]],
    issue_letsencrypt_certificate: Callable[..., dict[str, Any]],
) -> APIRouter:
    router = APIRouter()

    @router.post('/v1/admin/restart')
    def restart_server(background_tasks: BackgroundTasks, _auth: None = Depends(require_auth)) -> dict[str, str]:
        schedule_local_restart(background_tasks, 'PAC restart requested from Web UI')
        return {'status': 'restarting', 'note': 'PAC will restart through systemd when possible. If PAC was started manually, start it again with run.sh.'}

    @router.get('/v1/admin/service/status')
    def service_status(_auth: None = Depends(require_auth)) -> dict[str, Any]:
        return service_status_payload()

    @router.post('/v1/admin/service/mode')
    def set_service_mode(payload: ServiceModeRequest, background_tasks: BackgroundTasks, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        config = get_config()
        requested = (payload.mode or '').strip().lower()
        if requested not in ('user', 'host'):
            raise HTTPException(status_code=400, detail='mode must be user or host')
        service_name = getattr(config.service, 'name', 'pacp') if hasattr(config, 'service') else 'pacp'
        results: list[dict[str, Any]] = []
        if requested == 'host':
            tmp, unit = write_system_service_unit(service_name, 443)
            import os
            if os.getuid() == 0:
                results.append(run_quiet(['mv', str(tmp), str(unit)]))
                results.append(run_quiet(['systemctl', 'daemon-reload']))
                results.append(run_quiet(['systemctl', 'enable', '--now', service_name]))
                results.append(run_quiet(['systemctl', '--user', 'disable', '--now', service_name], timeout=8))
            elif can_sudo_noninteractive():
                results.append(run_quiet(['sudo', '-n', 'mv', str(tmp), str(unit)]))
                results.append(run_quiet(['sudo', '-n', 'systemctl', 'daemon-reload']))
                results.append(run_quiet(['sudo', '-n', 'systemctl', 'enable', '--now', service_name]))
                results.append(run_quiet(['systemctl', '--user', 'disable', '--now', service_name], timeout=8))
            else:
                return {'ok': False, 'needs_sudo': True, 'message': 'Host service requires sudo/root. Run the manual command shown, or start PAC with sudo once to switch modes.', 'status': service_status_payload(), 'prepared_unit': str(tmp)}
            config.service.mode = 'host'
            config.server.port = 443
            config.server.public_url = preserve_or_default_public_url(config.server.public_url, 443)
        else:
            user_port = user_service_port()
            write_user_service_unit(service_name, user_port)
            results.append(run_quiet(['systemctl', '--user', 'daemon-reload'], timeout=8))
            results.append(run_quiet(['systemctl', '--user', 'enable', '--now', service_name], timeout=8))
            import os
            if os.getuid() == 0:
                results.append(run_quiet(['systemctl', 'disable', '--now', service_name], timeout=8))
            elif can_sudo_noninteractive():
                results.append(run_quiet(['sudo', '-n', 'systemctl', 'disable', '--now', service_name], timeout=8))
            config.service.mode = 'user'
            config.server.port = user_port
            config.server.public_url = preserve_or_default_public_url(config.server.public_url, user_port)
        save_config(config)
        store.add_event(Event(session_id='system', type='service_mode_changed', message=f'PAC service mode set to {requested}', data={'mode': requested, 'results': results}))
        schedule_local_restart(background_tasks, f'PAC restart scheduled after switching service mode to {requested}')
        return {'ok': all(r.get('ok') for r in results if r.get('returncode') is not None), 'mode': requested, 'results': results, 'restart_scheduled': True, 'status': service_status_payload()}

    @router.get('/v1/tls/status')
    def tls_status(_auth: None = Depends(require_auth)) -> dict[str, Any]:
        config = get_config()
        status = ensure_tls_material()
        status['mdns'] = mdns_config()
        status['mdns_status'] = mdns_status()
        status['mdns_hostname'] = str(mdns_config().get('hostname', 'admin.pac.local'))
        suffix = '' if int(config.server.port) == 443 else f':{config.server.port}'
        status['mdns_url'] = f'https://{status["mdns_hostname"].rstrip(".")}{suffix}'
        status['port_443'] = {
            'configured': int(config.server.port) == 443,
            'requires': 'root, systemd AmbientCapabilities=CAP_NET_BIND_SERVICE, or a reverse proxy/socket activator',
        }
        return status

    @router.get('/v1/tls/ca.pem')
    def download_tls_ca(_auth: None = Depends(require_auth)):
        status = ensure_tls_material()
        path = Path(status['ca_cert_file'])
        if not path.exists():
            raise HTTPException(status_code=404, detail='PAC CA has not been generated yet')
        return FileResponse(path, media_type='application/x-pem-file', filename='pac-root-ca.crt')

    @router.post('/v1/tls/issue-endpoint-cert')
    def issue_endpoint_cert(payload: EndpointCertificateRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        return issue_endpoint_certificate(payload.name, payload.csr_pem, payload.sans, payload.days)

    @router.get('/v1/server/letsencrypt/status')
    def letsencrypt_status(_auth: None = Depends(require_auth)) -> dict[str, Any]:
        return get_letsencrypt_status()

    @router.post('/v1/server/letsencrypt/test-dns')
    def letsencrypt_test_dns(domain: str = Query(...), _auth: None = Depends(require_auth)) -> dict[str, Any]:
        return check_domain_dns(domain)

    @router.post('/v1/server/letsencrypt/test-cloudflare')
    def letsencrypt_test_cloudflare(api_token: str = Query(...), zone_id: str = Query(...), _auth: None = Depends(require_auth)) -> dict[str, Any]:
        return test_cloudflare_credentials(api_token, zone_id)

    @router.post('/v1/server/letsencrypt/enable')
    def letsencrypt_enable(payload: LetsEncryptEnableRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        config = get_config()
        domain = payload.domain.strip().lower()
        email = payload.email.strip()
        if not re.match(r'^[a-z0-9.-]+$', domain):
            return {'ok': False, 'error': 'Invalid domain name'}
        if '@' not in email:
            return {'ok': False, 'error': 'Invalid email address'}
        cred_test = test_cloudflare_credentials(payload.cloudflare_api_token, payload.cloudflare_zone_id)
        if not cred_test.get('ok'):
            return {'ok': False, 'error': f"Cloudflare credentials invalid: {cred_test.get('error')}"}
        le = config.letsencrypt
        le.email = email
        le.domain = domain
        le.cloudflare_api_token = payload.cloudflare_api_token
        le.cloudflare_zone_id = payload.cloudflare_zone_id
        le.auto_enable = payload.auto_enable
        le.enabled = False
        cert_dir = Path(le.cert_file).expanduser().parent
        cert_dir.mkdir(parents=True, exist_ok=True)
        save_config(config)
        store.add_event(Event(session_id='system', type='letsencrypt_started', message=f'Starting LE DNS-01 for {domain}', data={'domain': domain, 'email': email, 'staging': payload.staging}))
        result = issue_letsencrypt_certificate(domain, email, staging=payload.staging)
        if result.get('ok'):
            le.enabled = True
            save_config(config)
            store.add_event(Event(session_id='system', type='letsencrypt_cert_obtained', message=f"LE certificate obtained for {domain}", data={'cert_file': result.get('cert_file')}))
            return {'ok': True, 'message': f"Certificate obtained for {domain}", 'cert_file': result.get('cert_file'), 'key_file': result.get('key_file')}
        store.add_event(Event(session_id='system', type='letsencrypt_failed', message=f"LE failed: {result.get('error')}", data={'domain': domain}))
        return {'ok': False, 'error': result.get('error', 'Unknown error')}

    @router.post('/v1/server/letsencrypt/disable')
    def letsencrypt_disable(_auth: None = Depends(require_auth)) -> dict[str, Any]:
        config = get_config()
        config.letsencrypt.enabled = False
        save_config(config)
        store.add_event(Event(session_id='system', type='letsencrypt_disabled', message='Lets Encrypt disabled', data={}))
        return {'ok': True, 'message': 'Lets Encrypt disabled. Internal CA will be used.'}

    return router
