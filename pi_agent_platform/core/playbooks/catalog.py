from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..config import AppConfig
from ..platform_home import pacp_path
from .schema import Playbook

_BUILTIN_CODE_CHANGE = """
id: code-change-workflow
title: Code change workflow
description: Explore, plan, implement, verify, and package a code change.
version: "1"
tags: [code, default]
parameters:
  - name: instruction
    type: string
    required: true
    description: What should be changed or investigated.
  - name: require_approval
    type: boolean
    default: true
steps:
  - id: explore
    title: Explore codebase
    action: subagent_chain
    prompt: "Explore only: {instruction}"
  - id: plan_review
    title: Review implementation plan
    action: checkpoint
    depends_on: [explore]
    gate:
      type: review
      message: Review the exploration and plan before implementation.
  - id: implement
    title: Implement and verify
    action: subagent_chain
    depends_on: [plan_review]
    prompt: "Implement and verify: {instruction}"
  - id: final_checkpoint
    title: Final review
    action: checkpoint
    depends_on: [implement]
    gate:
      type: approve
      message: Approve the completed code change and package output.
"""

_BUILTIN_GIT_SESSION = """
id: git-workspace-session
title: Git workspace coding session
description: Create a git workspace profile, open a container-backed session, inspect the project, and prepare diagnostics.
version: "1"
tags: [workspace, git, coding]
parameters:
  - name: name
    type: string
    required: true
  - name: url
    type: string
    required: true
  - name: container_image
    type: string
    default: localhost/python-dev:latest
  - name: model
    type: string
    required: false
  - name: inspect_prompt
    type: string
    default: Check what this code entails and summarize the architecture.
steps:
  - id: create_workspace
    title: Create workspace profile
    action: tool
    tool: pac_create_workspace_profile
    input:
      name: "{name}"
      type: git
      url: "{url}"
      runtime: container
      container_image: "{container_image}"
      idempotent: true
  - id: create_session
    title: Create coding session
    action: tool
    tool: pac_create_session
    depends_on: [create_workspace]
    input:
      name: "{name}"
      workspace_profile: "{name}"
      model: "{model}"
      container_image: "{container_image}"
      expose_platform_tools: true
      metadata:
        coding_session: true
        source: playbook
    export:
      session_id: session.id
      readiness_status: coding_readiness.status
  - id: inspect
    title: Inspect project
    action: subagent_chain
    depends_on: [create_session]
    target_session_from: session_id
    when:
      output: readiness_status
      equals: ready
    prompt: "{inspect_prompt}"
  - id: ready_review
    title: Ready for review
    action: checkpoint
    depends_on: [inspect]
    gate:
      type: review
      message: Review the new workspace/session and inspection result.
"""


def _parse_yaml(text: str, source: str) -> Playbook:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Playbook {source} must be a YAML mapping")
    return Playbook.model_validate(data)


def built_in_playbooks() -> dict[str, Playbook]:
    items = [_BUILTIN_CODE_CHANGE, _BUILTIN_GIT_SESSION]
    result: dict[str, Playbook] = {}
    for item in items:
        playbook = _parse_yaml(item, "built-in")
        result[playbook.id] = playbook
    return result


def playbook_search_paths(config: AppConfig) -> list[Path]:
    root = Path(getattr(config.server, "data_dir", "~/.pacp")).expanduser()
    return [root / "playbooks", pacp_path("playbooks")]


def load_playbooks(config: AppConfig) -> tuple[dict[str, Playbook], list[dict[str, Any]]]:
    playbooks = built_in_playbooks()
    errors: list[dict[str, Any]] = []
    for directory in playbook_search_paths(config):
        if not directory.exists():
            continue
        for path in sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")]):
            try:
                playbook = _parse_yaml(path.read_text(encoding="utf-8"), str(path))
                playbooks[playbook.id] = playbook
            except Exception as exc:
                errors.append({"path": str(path), "error": str(exc)})
    return playbooks, errors


def get_playbook(config: AppConfig, playbook_id: str) -> Playbook:
    playbooks, errors = load_playbooks(config)
    if playbook_id not in playbooks:
        detail = f"Unknown playbook: {playbook_id}"
        if errors:
            detail += f". Load errors: {errors[:3]}"
        raise KeyError(detail)
    return playbooks[playbook_id]
