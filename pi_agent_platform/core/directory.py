from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import DirectoryMember, DirectoryPrincipal, Event, Group, ResourceGrant, User, now_utc

PAC_ADMIN_GROUP_ID = 'pacadm:admins'
LEGACY_ADMIN_GROUP_IDS = {'admin', 'admins', 'pacadm:admins'}


@dataclass(frozen=True)
class MembershipPath:
    group_id: str
    path: tuple[str, ...]


def normalize_group_id(value: str) -> str:
    text = str(value or '').strip()
    if not text:
        return text
    if text in LEGACY_ADMIN_GROUP_IDS:
        return PAC_ADMIN_GROUP_ID
    return text


def public_member(member: DirectoryMember) -> dict[str, str]:
    return {'kind': member.kind, 'id': member.id}


def public_principal(principal: DirectoryPrincipal) -> dict[str, Any]:
    return {
        'id': principal.id,
        'kind': principal.kind,
        'name': principal.name,
        'display_name': principal.display_name or principal.name,
        'description': principal.description,
        'status': principal.status,
        'source': principal.source,
        'system_managed': principal.system_managed,
        'created_at': principal.created_at.isoformat(),
        'updated_at': principal.updated_at.isoformat(),
        'metadata': principal.metadata or {},
    }


def group_has_member(group: Group, kind: str, member_id: str) -> bool:
    return any(item.kind == kind and item.id == member_id for item in (group.members or []))


def add_member_to_group(store: Any, group_id: str, member: DirectoryMember) -> Group:
    group_id = normalize_group_id(group_id)
    group = store.get_group(group_id)
    if not group:
        raise KeyError(f'Group not found: {group_id}')
    if member.kind == 'group':
        member.id = normalize_group_id(member.id)
        if member.id == group.id:
            raise ValueError('A group cannot contain itself')
        if would_create_group_cycle(store, parent_group_id=group.id, child_group_id=member.id):
            raise ValueError('Group membership would create a cycle')
    if not group_has_member(group, member.kind, member.id):
        group.members.append(member)
        store.add_group(group)
    return group


def remove_member_from_group(store: Any, group_id: str, kind: str, member_id: str) -> Group:
    group_id = normalize_group_id(group_id)
    group = store.get_group(group_id)
    if not group:
        raise KeyError(f'Group not found: {group_id}')
    member_id = normalize_group_id(member_id) if kind == 'group' else member_id
    group.members = [item for item in (group.members or []) if not (item.kind == kind and item.id == member_id)]
    store.add_group(group)
    return group


def child_group_ids(group: Group) -> list[str]:
    return [normalize_group_id(item.id) for item in (group.members or []) if item.kind == 'group']


def would_create_group_cycle(store: Any, parent_group_id: str, child_group_id: str) -> bool:
    parent_group_id = normalize_group_id(parent_group_id)
    child_group_id = normalize_group_id(child_group_id)
    if parent_group_id == child_group_id:
        return True
    stack = [child_group_id]
    seen: set[str] = set()
    while stack:
        current_id = normalize_group_id(stack.pop())
        if current_id in seen:
            continue
        if current_id == parent_group_id:
            return True
        seen.add(current_id)
        child = store.get_group(current_id)
        if child:
            stack.extend(child_group_ids(child))
    return False


def resolve_direct_group_ids(store: Any, principal_id: str, principal_kind: str = 'user') -> set[str]:
    principal_id = str(principal_id or '').strip()
    direct: set[str] = set()
    if not principal_id:
        return direct
    for group in store.list_groups():
        if group_has_member(group, principal_kind, principal_id):
            direct.add(group.id)
    return direct


def resolve_effective_group_paths(store: Any, principal_id: str, principal_kind: str = 'user') -> list[MembershipPath]:
    direct = sorted(resolve_direct_group_ids(store, principal_id, principal_kind))
    paths: dict[str, tuple[str, ...]] = {group_id: (group_id,) for group_id in direct}
    queue: list[tuple[str, tuple[str, ...]]] = [(group_id, (group_id,)) for group_id in direct]
    while queue:
        child_id, path = queue.pop(0)
        for group in store.list_groups():
            if group.id in paths:
                continue
            if group_has_member(group, 'group', child_id):
                next_path = path + (group.id,)
                paths[group.id] = next_path
                queue.append((group.id, next_path))
    return [MembershipPath(group_id=group_id, path=path) for group_id, path in sorted(paths.items())]


def resolve_effective_group_ids(store: Any, principal_id: str, principal_kind: str = 'user') -> set[str]:
    return {item.group_id for item in resolve_effective_group_paths(store, principal_id, principal_kind)}


def explain_principal_membership(store: Any, principal_id: str, principal_kind: str = 'user') -> dict[str, Any]:
    direct = resolve_direct_group_ids(store, principal_id, principal_kind)
    paths = resolve_effective_group_paths(store, principal_id, principal_kind)
    return {
        'principal_id': principal_id,
        'principal_kind': principal_kind,
        'direct_groups': sorted(direct),
        'effective_groups': [
            {'id': item.group_id, 'direct': item.group_id in direct, 'path': list(item.path)}
            for item in paths
        ],
    }


def build_directory_tree(store: Any) -> dict[str, Any]:
    users = store.list_users()
    groups = store.list_groups()
    directory_principals = store.list_directory_principals() if hasattr(store, 'list_directory_principals') else []
    service_accounts = [item for item in directory_principals if item.kind == 'service_account']
    endpoint_principals = [item for item in directory_principals if item.kind == 'endpoint']
    provider_principals = [item for item in directory_principals if item.kind == 'provider']
    certificate_identities = [item for item in directory_principals if item.kind == 'certificate_identity']
    user_nodes = [
        {
            'id': user.id,
            'kind': 'user',
            'name': user.username,
            'display_name': user.display_name or user.username,
            'status': 'active',
            'source': 'local',
        }
        for user in users
    ]
    group_nodes = []
    for group in groups:
        group_nodes.append({
            'id': group.id,
            'kind': 'group',
            'name': group.name,
            'description': group.description,
            'source': group.source,
            'system_managed': group.system_managed,
            'members': [public_member(item) for item in (group.members or [])],
            'grants': [grant.model_dump() for grant in (group.grants or [])],
        })
    return {
        'roots': [
            {'id': 'people', 'kind': 'folder', 'name': 'People', 'children': [{'kind': 'user', 'id': item['id']} for item in user_nodes]},
            {'id': 'groups', 'kind': 'folder', 'name': 'Groups', 'children': [{'kind': 'group', 'id': item['id']} for item in group_nodes]},
            {'id': 'service_accounts', 'kind': 'folder', 'name': 'Service Accounts', 'children': [{'kind': 'service_account', 'id': item.id} for item in service_accounts]},
            {'id': 'endpoints', 'kind': 'folder', 'name': 'Endpoints', 'children': [{'kind': 'endpoint', 'id': item.id} for item in endpoint_principals]},
            {'id': 'providers', 'kind': 'folder', 'name': 'Providers', 'children': [{'kind': 'provider', 'id': item.id} for item in provider_principals]},
            {'id': 'certificate_identities', 'kind': 'folder', 'name': 'Certificate Identities', 'children': [{'kind': 'certificate_identity', 'id': item.id} for item in certificate_identities]},
        ],
        'users': user_nodes,
        'groups': group_nodes,
        'service_accounts': [public_principal(item) for item in service_accounts],
        'endpoints': [public_principal(item) for item in endpoint_principals],
        'providers': [public_principal(item) for item in provider_principals],
        'certificate_identities': [public_principal(item) for item in certificate_identities],
        'principals': [public_principal(item) for item in directory_principals],
    }


def ensure_pac_admin_group(store: Any) -> Group:
    existing = store.get_group(PAC_ADMIN_GROUP_ID)
    if existing:
        changed = False
        if existing.source != 'pac':
            existing.source = 'pac'; changed = True
        if not existing.system_managed:
            existing.system_managed = True; changed = True
        if changed:
            store.add_group(existing)
        return existing
    group = Group(
        id=PAC_ADMIN_GROUP_ID,
        name='PAC Admins',
        description='Built-in PAC administrators with system management access.',
        source='pac',
        system_managed=True,
        metadata={'builtin': True, 'admin_group': True},
    )
    store.add_group(group)
    return group


def _legacy_user_payloads(store: Any) -> list[dict[str, Any]]:
    if hasattr(store, 'list_raw_user_payloads'):
        return [item for item in store.list_raw_user_payloads() if isinstance(item, dict)]
    payloads: list[dict[str, Any]] = []
    for user in store.list_users():
        payloads.append(user.model_dump(mode='json'))
    return payloads


def _group_for_migrated_user_grants(store: Any, user_id: str) -> Group:
    safe = ''.join(ch if ch.isalnum() or ch in {':', '_', '-'} else '-' for ch in str(user_id or '').strip())
    group_id = f'pacusr:user:{safe}'
    group = store.get_group(group_id)
    if not group:
        group = Group(
            id=group_id,
            name=f'Direct grants for {user_id}',
            description='System-managed directory group imported from legacy user metadata grants.',
            source='pac',
            system_managed=True,
            members=[DirectoryMember(kind='user', id=user_id)],
            metadata={'direct_grant_group': True, 'principal_kind': 'user', 'principal_id': user_id, 'legacy_import': True},
        )
    elif not group_has_member(group, 'user', user_id):
        group.members.append(DirectoryMember(kind='user', id=user_id))
    return group


def migrate_legacy_user_groups(store: Any) -> dict[str, Any]:
    """Destructively import removed user authorization fields into directory groups.

    Pass 5 removes User.groups and direct user metadata grants from runtime auth.
    This migration reads old raw user payloads, converts memberships into
    Group.members, converts metadata.resource_grants into pacusr:* directory
    groups, and rewrites user rows through the new User model so old fields are
    discarded from persisted JSON.
    """
    created_groups = 0
    memberships_added = 0
    users_rewritten = 0
    direct_grants_imported = 0
    admin_group = ensure_pac_admin_group(store)
    raw_by_id = {str(item.get('id') or item.get('username') or '').strip(): item for item in _legacy_user_payloads(store)}
    for user in store.list_users():
        raw = raw_by_id.get(user.id, {})
        imported_group_ids = [normalize_group_id(item) for item in (raw.get('groups') or []) if str(item).strip()]
        if user.role == 'admin' and PAC_ADMIN_GROUP_ID not in imported_group_ids:
            imported_group_ids.append(PAC_ADMIN_GROUP_ID)
        for group_id in sorted(set(imported_group_ids)):
            group = store.get_group(group_id)
            if not group:
                group = Group(id=group_id, name=group_id, source='local')
                store.add_group(group)
                created_groups += 1
            before = len(group.members or [])
            if not group_has_member(group, 'user', user.id):
                group.members.append(DirectoryMember(kind='user', id=user.id))
                store.add_group(group)
            if len(group.members or []) > before:
                memberships_added += 1
        metadata = dict(user.metadata or {})
        raw_grants = metadata.pop('resource_grants', None)
        if isinstance(raw_grants, list):
            grant_group = _group_for_migrated_user_grants(store, user.id)
            before = len(grant_group.grants or [])
            for item in raw_grants:
                try:
                    grant = ResourceGrant.model_validate(item)
                except Exception:
                    continue
                if not any(existing.resource_type == grant.resource_type and existing.pattern == grant.pattern and existing.access == grant.access for existing in grant_group.grants):
                    grant_group.grants.append(grant)
            if len(grant_group.grants or []) != before:
                direct_grants_imported += len(grant_group.grants or []) - before
                store.add_group(grant_group)
        if metadata != (user.metadata or {}) or raw.get('groups') is not None:
            user.metadata = metadata
            store.add_user(user)
            users_rewritten += 1
    return {
        'pac_admin_group': admin_group.id,
        'created_groups': created_groups,
        'memberships_added': memberships_added,
        'direct_grants_imported': direct_grants_imported,
        'users_rewritten': users_rewritten,
    }
