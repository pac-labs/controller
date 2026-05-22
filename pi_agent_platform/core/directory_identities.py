from __future__ import annotations

from typing import Any

from .access_control import grant_to_principal
from .models import DirectoryPrincipal, ResourceGrant, Runner, now_utc


def ensure_principal_group_grant(
    store: Any,
    *,
    principal_kind: str,
    principal_id: str,
    resource_type: str,
    resource_id: str,
    access: str,
) -> None:
    grant_to_principal(
        store,
        principal_kind,
        principal_id,
        ResourceGrant(resource_type=resource_type, pattern=resource_id, access=access),
    )


def ensure_endpoint_principal(store: Any, runner: Runner) -> DirectoryPrincipal:
    """Create/update the directory principal that represents an endpoint runner."""
    existing = store.get_directory_principal(runner.id) if hasattr(store, 'get_directory_principal') else None
    metadata = {
        **(existing.metadata if existing else {}),
        'runner_id': runner.id,
        'endpoint': runner.endpoint,
        'labels': list(runner.labels or []),
        'status': runner.status.value if hasattr(runner.status, 'value') else str(runner.status),
        'local_control_plane': bool((runner.metadata or {}).get('local_control_plane')),
        'directory_managed_by': 'endpoint_registration',
    }
    principal = DirectoryPrincipal(
        id=runner.id,
        kind='endpoint',
        name=runner.name or runner.id,
        display_name=runner.name or runner.id,
        description='PAC endpoint identity',
        status='active' if str(metadata.get('status', '')).lower() not in {'disabled'} else 'disabled',
        source='pac',
        system_managed=True,
        created_at=existing.created_at if existing else runner.created_at,
        metadata=metadata,
    )
    store.add_directory_principal(principal)
    ensure_principal_group_grant(store, principal_kind='endpoint', principal_id=runner.id, resource_type='endpoint', resource_id=runner.id, access='execute')
    return principal


def retire_endpoint_principal(store: Any, runner_id: str) -> None:
    principal = store.get_directory_principal(runner_id) if hasattr(store, 'get_directory_principal') else None
    if principal and principal.kind == 'endpoint':
        principal.status = 'disabled'
        principal.metadata = {**(principal.metadata or {}), 'retired': True}
        store.add_directory_principal(principal)
    for credential in list(store.list_directory_credentials(principal_id=runner_id)):
        credential.status = 'revoked'
        store.add_directory_credential(credential)


def ensure_provider_principal(store: Any, provider_name: str, provider: Any) -> DirectoryPrincipal:
    """Create/update the directory principal that represents a model provider."""
    existing = store.get_directory_principal(provider_name) if hasattr(store, 'get_directory_principal') else None
    metadata = {
        **(existing.metadata if existing else {}),
        'provider_name': provider_name,
        'provider_type': getattr(provider, 'type', None),
        'status': getattr(provider, 'status', None),
        'enabled': bool(getattr(provider, 'enabled', False)),
        'directory_managed_by': 'provider_registration',
    }
    principal = DirectoryPrincipal(
        id=provider_name,
        kind='provider',
        name=provider_name,
        display_name=getattr(provider, 'display_name', None) or provider_name,
        description='PAC model provider identity',
        status='active' if bool(getattr(provider, 'enabled', False)) else 'disabled',
        source='pac',
        system_managed=True,
        created_at=existing.created_at if existing else now_utc(),
        metadata=metadata,
    )
    store.add_directory_principal(principal)
    ensure_principal_group_grant(store, principal_kind='provider', principal_id=provider_name, resource_type='provider', resource_id=provider_name, access='use')
    return principal


def retire_provider_principal(store: Any, provider_name: str) -> None:
    principal = store.get_directory_principal(provider_name) if hasattr(store, 'get_directory_principal') else None
    if principal and principal.kind == 'provider':
        principal.status = 'disabled'
        principal.metadata = {**(principal.metadata or {}), 'retired': True}
        store.add_directory_principal(principal)
    for credential in list(store.list_directory_credentials(principal_id=provider_name)):
        credential.status = 'revoked'
        store.add_directory_credential(credential)


def sync_directory_identities(store: Any, *, runners: list[Runner], providers: dict[str, Any]) -> dict[str, int]:
    endpoint_count = 0
    provider_count = 0
    for runner in runners:
        ensure_endpoint_principal(store, runner)
        endpoint_count += 1
    for name, provider in providers.items():
        ensure_provider_principal(store, name, provider)
        provider_count += 1
    return {'endpoints': endpoint_count, 'providers': provider_count}
