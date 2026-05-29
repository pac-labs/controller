from __future__ import annotations

import fnmatch
from typing import Any

from .directory import PAC_ADMIN_GROUP_ID, resolve_effective_group_ids, resolve_effective_group_paths
from .models import DirectoryMember, Group, ResourceGrant, User


def resource_match(rule: ResourceGrant, resource_type: str, resource_id: str, access: str) -> bool:
    if rule.resource_type != resource_type:
        return False
    if not _access_allows(rule.access, access):
        return False
    return fnmatch.fnmatch(str(resource_id), str(rule.pattern))


def _access_allows(granted: str, requested: str) -> bool:
    hierarchy = {
        'read': {'read'},
        'use': {'read', 'use'},
        'execute': {'read', 'use', 'execute'},
        'write': {'read', 'use', 'execute', 'write'},
        'manage': {'read', 'use', 'execute', 'write', 'manage'},
    }
    return requested in hierarchy.get(str(granted), {str(granted)})


def _subject_ref(subject: Any) -> tuple[str, str, User | None, bool]:
    """Return principal_id, principal_kind, user, controller_auth.

    Route code should pass CurrentUser. User is still accepted for older callers,
    but it is converted into a directory principal reference immediately.
    """
    if subject is None:
        return 'controller', 'controller', None, True
    if isinstance(subject, User):
        return subject.id, 'user', subject, False
    principal_id = getattr(subject, 'principal_id', None)
    if callable(principal_id):
        principal_id = principal_id()
    principal_id = str(principal_id or '').strip()
    principal_kind = str(getattr(subject, 'principal_kind', '') or '').strip()
    user = getattr(subject, 'user', None)
    if principal_id:
        return principal_id, principal_kind or ('user' if user else 'service_account'), user, principal_id == 'controller'
    if user:
        return user.id, 'user', user, False
    return 'controller', 'controller', None, True



def effective_grants(store: Any, subject: Any) -> list[ResourceGrant]:
    principal_id, principal_kind, _user, controller_auth = _subject_ref(subject)
    if controller_auth:
        return [ResourceGrant(resource_type='system', pattern='*', access='manage')]
    grants: list[ResourceGrant] = []
    group_ids = resolve_effective_group_ids(store, principal_id, principal_kind)
    for group in store.list_groups():
        if group.id in group_ids:
            grants.extend(group.grants or [])
    return grants


def is_system_admin(store: Any, subject: Any) -> bool:
    principal_id, principal_kind, _user, controller_auth = _subject_ref(subject)
    if controller_auth:
        return True
    return PAC_ADMIN_GROUP_ID in resolve_effective_group_ids(store, principal_id, principal_kind)


def can(
    store: Any,
    subject: Any,
    resource_type: str,
    resource_id: str,
    access: str = 'read',
    *,
    owner_id: str | None = None,
    allowed_groups: list[str] | set[str] | tuple[str, ...] | None = None,
    allow_unrestricted: bool = False,
) -> bool:
    principal_id, principal_kind, _user, controller_auth = _subject_ref(subject)
    if controller_auth or is_system_admin(store, subject):
        return True
    if owner_id and principal_id == str(owner_id):
        return True
    group_ids = resolve_effective_group_ids(store, principal_id, principal_kind)
    allowed = {str(item).strip() for item in (allowed_groups or []) if str(item).strip()}
    if allowed:
        if group_ids & allowed:
            return True
    elif allow_unrestricted:
        return True
    return any(resource_match(grant, resource_type, resource_id, access) for grant in effective_grants(store, subject))


def require(store: Any, subject: Any, resource_type: str, resource_id: str, access: str = 'read', **kwargs: Any) -> None:
    if not can(store, subject, resource_type, resource_id, access, **kwargs):
        raise PermissionError(f'{access} access required for {resource_type}:{resource_id}')


def explain(store: Any, subject: Any, resource_type: str | None = None, resource_id: str | None = None, access: str = 'read') -> dict[str, Any]:
    principal_id, principal_kind, _user, controller_auth = _subject_ref(subject)
    if controller_auth:
        return {'principal_id': 'controller', 'principal_kind': 'controller', 'admin': True, 'groups': [], 'grants': []}
    group_paths = {item.group_id: list(item.path) for item in resolve_effective_group_paths(store, principal_id, principal_kind)}
    grants: list[dict[str, Any]] = []
    for group in store.list_groups():
        if group.id not in group_paths:
            continue
        for grant in (group.grants or []):
            grants.append({'source': 'group', 'source_id': group.id, 'path': group_paths[group.id], 'grant': grant.model_dump(), 'matches': _grant_matches(grant, resource_type, resource_id, access)})
    return {
        'principal_id': principal_id,
        'principal_kind': principal_kind,
        'admin': is_system_admin(store, subject),
        'groups': [{'id': group_id, 'path': path} for group_id, path in sorted(group_paths.items())],
        'grants': grants,
    }


def explain_access(store: Any, subject: Any, resource_type: str | None = None, resource_id: str | None = None, access: str = 'read') -> dict[str, Any]:
    return explain(store, subject, resource_type, resource_id, access)


def _grant_matches(grant: ResourceGrant, resource_type: str | None, resource_id: str | None, access: str) -> bool | None:
    if resource_type is None or resource_id is None:
        return None
    return resource_match(grant, resource_type, resource_id, access)


def directory_grant_group_id(principal_kind: str, principal_id: str) -> str:
    safe = ''.join(ch if ch.isalnum() or ch in {':', '_', '-'} else '-' for ch in str(principal_id or '').strip())
    return f'pacusr:{principal_kind}:{safe}'


def grant_to_principal(store: Any, principal_kind: str, principal_id: str, grant: ResourceGrant) -> Group:
    """Attach a grant to a system-managed per-principal directory group."""
    group_id = directory_grant_group_id(principal_kind, principal_id)
    group = store.get_group(group_id)
    if not group:
        group = Group(
            id=group_id,
            name=f'Direct grants for {principal_id}',
            description='System-managed group that stores direct grants without resurrecting User.groups.',
            source='pac',
            system_managed=True,
            members=[DirectoryMember(kind=principal_kind, id=principal_id)],
            metadata={'direct_grant_group': True, 'principal_kind': principal_kind, 'principal_id': principal_id},
        )
    elif not any(member.kind == principal_kind and member.id == principal_id for member in group.members):
        group.members.append(DirectoryMember(kind=principal_kind, id=principal_id))
    if not any(existing.resource_type == grant.resource_type and existing.pattern == grant.pattern and existing.access == grant.access for existing in group.grants):
        group.grants.append(grant)
    store.add_group(group)
    return group
