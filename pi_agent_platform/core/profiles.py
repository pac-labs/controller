from __future__ import annotations

from typing import Any


DEFAULT_PROFILE_INSTRUCTIONS = "You are a careful remote coding and infrastructure agent."


def profile_display_name(name: str, profile: Any) -> str:
    display_name = str(getattr(profile, "display_name", "") or "").strip()
    return display_name or name


def profile_instructions(profile: Any) -> str:
    instructions = str(getattr(profile, "instructions", "") or "").strip()
    if instructions:
        return instructions
    legacy = str(getattr(profile, "system_prompt", "") or "").strip()
    return legacy or DEFAULT_PROFILE_INSTRUCTIONS


def profile_context_name(profile: Any, fallback: str = "medium") -> str:
    context_profile = str(getattr(profile, "context_profile", "") or "").strip()
    if context_profile:
        return context_profile
    legacy = str(getattr(profile, "context_mode", "") or "").strip()
    return legacy or fallback


def profile_planner_context_name(profile: Any, fallback: str | None = None) -> str | None:
    planner_context = str(getattr(profile, "planner_context_profile", "") or "").strip()
    if planner_context:
        return planner_context
    return fallback


def profile_allowed_groups(profile: Any) -> list[str]:
    return [str(item).strip() for item in (getattr(profile, "allowed_groups", None) or []) if str(item).strip()]


def profile_visibility(profile: Any) -> str:
    value = str(getattr(profile, "visibility", "") or "").strip()
    if value:
        return value
    return "group" if profile_allowed_groups(profile) else "global"


def profile_output_preferences(profile: Any) -> dict[str, Any]:
    raw = getattr(profile, "output_preferences", None) or {}
    return dict(raw) if isinstance(raw, dict) else {}


def auth_group_ids(auth: Any) -> set[str]:
    group_ids = getattr(auth, "group_ids", None)
    if group_ids is not None:
        value = group_ids() if callable(group_ids) else group_ids
        return {str(item).strip() for item in (value or set()) if str(item).strip()}
    return set()


def can_use_profile(profile: Any, auth: Any, *, store: Any | None = None, profile_name: str = "*") -> bool:
    allowed = set(profile_allowed_groups(profile))
    if store is not None:
        from .access_control import can as access_can

        return access_can(
            store,
            auth,
            "profile",
            profile_name or "*",
            "use",
            allowed_groups=allowed,
            allow_unrestricted=not allowed,
        )
    if getattr(auth, "is_admin", False) or not getattr(auth, "user", None):
        return True
    if not allowed:
        return True
    return bool(auth_group_ids(auth) & allowed)


def public_profile_payload(name: str, profile: Any, auth: Any, *, include_legacy: bool = False, store: Any | None = None) -> dict[str, Any]:
    data = {
        "name": name,
        "display_name": profile_display_name(name, profile),
        "description": str(getattr(profile, "description", "") or "").strip() or None,
        "instructions": profile_instructions(profile),
        "context_profile": profile_context_name(profile),
        "planner_context_profile": profile_planner_context_name(profile),
        "permission_profile": str(getattr(profile, "permission_profile", "") or "").strip() or "ask-first",
        "output_preferences": profile_output_preferences(profile),
        "allowed_groups": profile_allowed_groups(profile),
        "visibility": profile_visibility(profile),
        "max_agent_steps": getattr(profile, "max_agent_steps", None),
        "max_runtime_minutes": getattr(profile, "max_runtime_minutes", None),
        "can_use": can_use_profile(profile, auth, store=store, profile_name=name),
    }
    if include_legacy:
        data["model"] = getattr(profile, "model", None)
        data["planner_model"] = getattr(profile, "planner_model", None)
        data["tools"] = list(getattr(profile, "tools", None) or [])
        data["context_mode"] = getattr(profile, "context_mode", None)
        data["system_prompt"] = getattr(profile, "system_prompt", None)
    return data
