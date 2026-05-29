from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..platform_home import pacp_path
from .catalog import get_playbook, load_playbooks
from .schema import Playbook


def writable_playbooks_dir() -> Path:
    path = pacp_path('playbooks')
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(value: str) -> str:
    cleaned = ''.join(ch if ch.isalnum() or ch in {'-', '_', '.'} else '-' for ch in value.strip())
    return cleaned.strip('.-') or 'playbook'


def playbook_to_yaml(playbook: Playbook) -> str:
    data = playbook.model_dump(mode='json', exclude_none=True)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def export_playbook_yaml(config: Any, playbook_id: str) -> str:
    return playbook_to_yaml(get_playbook(config, playbook_id))


def import_playbook_yaml(config: Any, text: str, *, overwrite: bool = False) -> Playbook:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError('Playbook YAML must be a mapping')
    playbook = Playbook.model_validate(data)
    existing, _errors = load_playbooks(config)
    if playbook.id in existing and not overwrite:
        raise ValueError(f'Playbook {playbook.id} already exists; enable overwrite to replace it')
    path = writable_playbooks_dir() / f'{_safe_name(playbook.id)}.yaml'
    path.write_text(playbook_to_yaml(playbook), encoding='utf-8')
    return playbook
