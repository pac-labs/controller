"""PAC-RAM: Remote Access Memory for PAC profiles, users and workspaces."""
from pathlib import Path
from typing import Optional
import json, datetime, os

def _config():
    data_dir = os.environ.get('PACP_DATA_DIR', '/home/dorbian/.pacp')
    return Path(data_dir)

def pacp_path(name: str) -> Path:
    return _config() / name

def profile_ram_path(profile: str) -> Path:
    return pacp_path('profile-memory') / profile / 'pac-ram-profile.md'

def user_ram_path(user_id: str) -> Path:
    return pacp_path('users') / user_id / 'pac-ram-user.md'

def workspace_ram_path(workspace: str) -> Path:
    return pacp_path('workspaces') / workspace / 'pac-ram-workspace.md'

def ensure_profile_ram(profile: str) -> Path:
    p = profile_ram_path(profile)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(f"""=== PAC-RAM-PROFILE v1 ===
# Profile: {profile}
timestamp: {datetime.datetime.utcnow().isoformat()}Z
profile_mode: {profile}

## Context
[Describe how this profile operates, its purpose and constraints]

## Settings
[Key=value pairs this profile's agent should read into context]

## Skills
[Profile-specific skill references and configurations]

---
""")
    return p

def ensure_user_ram(user_id: str) -> Path:
    p = user_ram_path(user_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(f"""=== PAC-RAM-USER v1 ===
# User: {user_id}
timestamp: {datetime.datetime.utcnow().isoformat()}Z

## Preferences
[How this user likes to be addressed, their timezone, what they care about]

## Personalization
[Things the agent should remember and maintain about this user]

## Communication Style
[How this user prefers the agent to communicate]

---
""")
    return p

def ensure_workspace_ram(workspace: str) -> Path:
    p = workspace_ram_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(f"""=== PAC-RAM-WORKSPACE v1 ===
# Workspace: {workspace}
timestamp: {datetime.datetime.utcnow().isoformat()}Z

## State
[Current workspace state, active context, ongoing tasks]

## Notes
[Workspace-specific information the agent should maintain]

---
""")
    return p

def read_profile_ram(profile: str) -> dict:
    p = ensure_profile_ram(profile)
    return {'path': str(p), 'exists': p.exists(), 'content': p.read_text() if p.exists() else ''}

def read_user_ram(user_id: str) -> dict:
    p = ensure_user_ram(user_id)
    return {'path': str(p), 'exists': p.exists(), 'content': p.read_text() if p.exists() else ''}

def read_workspace_ram(workspace: str) -> dict:
    p = ensure_workspace_ram(workspace)
    return {'path': str(p), 'exists': p.exists(), 'content': p.read_text() if p.exists() else ''}

def write_profile_ram(profile: str, content: str) -> dict:
    p = ensure_profile_ram(profile)
    p.write_text(content)
    return {'ok': True, 'path': str(p), 'size': len(content)}

def write_user_ram(user_id: str, content: str) -> dict:
    p = ensure_user_ram(user_id)
    p.write_text(content)
    return {'ok': True, 'path': str(p), 'size': len(content)}

def write_workspace_ram(workspace: str, content: str) -> dict:
    p = ensure_workspace_ram(workspace)
    p.write_text(content)
    return {'ok': True, 'path': str(p), 'size': len(content)}

def list_user_ids() -> list[str]:
    users_dir = pacp_path('users')
    if not users_dir.exists():
        return []
    return [d.name for d in users_dir.iterdir() if d.is_dir()]

def list_workspaces() -> list[str]:
    ws_dir = pacp_path('workspaces')
    if not ws_dir.exists():
        return []
    return [d.name for d in ws_dir.iterdir() if d.is_dir()]

def list_profiles() -> list[str]:
    pm_dir = pacp_path('profile-memory')
    if not pm_dir.exists():
        return []
    return [d.name for d in pm_dir.iterdir() if d.is_dir()]
