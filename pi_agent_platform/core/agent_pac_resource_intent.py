from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PacResourcePlan:
    applies: bool
    name: str
    url: str | None
    container_image: str | None
    needs_workspace: bool
    needs_session: bool


def parse_pac_resource_plan(prompt: str) -> PacResourcePlan:
    compact = " ".join(str(prompt or "").split())
    lower = compact.lower()
    url = _extract_repo_url(compact)
    if not _looks_like_pac_resource_request(lower, url=url):
        return PacResourcePlan(False, "workspace", None, None, False, False)
    name = _resource_name_from_prompt(compact, url=url)
    needs_workspace = "workspace" in lower or bool(url)
    profile_only = _looks_profile_only(lower)
    implicit_programming_session = bool(url) and not profile_only
    needs_session = "session" in lower or implicit_programming_session
    return PacResourcePlan(
        applies=True,
        name=name,
        url=url,
        container_image=_container_image_from_prompt(lower),
        needs_workspace=needs_workspace,
        needs_session=needs_session,
    )


def workspace_profile_action(plan: PacResourcePlan) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": plan.name,
        "description": f"Git workspace for {plan.url}" if plan.url else f"Workspace {plan.name}",
        "type": "git" if plan.url else "local",
        "runtime": "container" if plan.container_image else "any",
    }
    if plan.url:
        payload["url"] = plan.url
    payload["idempotent"] = True
    if plan.container_image:
        payload["container_image"] = plan.container_image
    return {"type": "tool_call", "tool": "pac_create_workspace_profile", "input": payload}


def session_action(plan: PacResourcePlan) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "purpose": "programming",
        "created_from_workspace_request": True,
        "coding_session": True,
        "agent_enabled": True,
        "execution_mode": "container",
        "preferred_execution_mode": "container",
    }
    if plan.container_image:
        metadata["container_image"] = plan.container_image
    payload: dict[str, Any] = {
        "name": plan.name,
        "workspace_profile": plan.name,
        "permission_profile": "full-control",
        "expose_platform_tools": True,
        "metadata": metadata,
        "idempotent": True,
    }
    if plan.container_image:
        payload["container_image"] = plan.container_image
    return {"type": "tool_call", "tool": "pac_create_session", "input": payload}


def _looks_like_pac_resource_request(lower: str, *, url: str | None = None) -> bool:
    compact = " ".join(str(lower or "").split())
    resource_terms = ("workspace", "session", "endpoint", "provider", "model")
    has_resource_term = any(term in compact for term in resource_terms)
    if not has_resource_term:
        return False

    # Git-backed workspace prompts are control-plane resource requests even when
    # the user types imperfect imperative text such as "please c reate".  Treat
    # the repository URL plus a resource word as stronger evidence than an exact
    # action prefix so the agent does not fall back into codebase inspection.
    if url and ("workspace" in compact or "session" in compact):
        return True

    has_action = _has_resource_action(compact)
    has_pac_or_repo_context = "http://" in compact or "https://" in compact or " pac " in f" {compact} " or "session" in compact
    return has_action and has_pac_or_repo_context


def _has_resource_action(compact: str) -> bool:
    if compact.startswith(("create ", "add ", "make ", "set up ", "setup ", "please create ", "please add ")):
        return True
    return bool(re.search(r"\b(?:please\s+)?c\s*reate\b", compact))


def _looks_profile_only(lower: str) -> bool:
    compact = " ".join(str(lower or "").split())
    return any(
        phrase in compact
        for phrase in (
            "profile only",
            "workspace profile only",
            "only the workspace profile",
            "do not create a session",
            "without a session",
            "no session",
        )
    )


def _extract_repo_url(prompt: str) -> str | None:
    match = re.search(r"https?://[^\s,;]+", prompt)
    if not match:
        return None
    return match.group(0).rstrip(".,;)")


def _resource_name_from_prompt(prompt: str, *, url: str | None) -> str:
    if url:
        tail = url.rstrip("/").split("/")[-1]
        tail = re.sub(r"\.git$", "", tail, flags=re.IGNORECASE)
        name = re.sub(r"[^A-Za-z0-9_.-]+", "-", tail).strip("-._")
        if name:
            return name
    return "workspace"


def _container_image_from_prompt(lower: str) -> str | None:
    if "rust" in lower:
        return "rust:latest"
    if "node" in lower or "javascript" in lower or "typescript" in lower:
        return "node:20-bookworm"
    if "python" in lower:
        return "python:3.12-slim"
    if "golang" in lower or " go " in f" {lower} ":
        return "golang:1.23"
    return None
