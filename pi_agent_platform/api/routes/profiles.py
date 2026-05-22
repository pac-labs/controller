from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from pi_agent_platform.core.config import AgentProfile, MAIN_PI_DEV_PROFILE
from pi_agent_platform.core.models import Event
from pi_agent_platform.core.profiles import can_use_profile, public_profile_payload


def create_profiles_router(
    *,
    require_auth: Any,
    get_config: Any,
    save_config: Any,
    store: Any,
) -> APIRouter:
    router = APIRouter()

    def _validated_allowed_groups(payload: dict[str, Any]) -> list[str]:
        allowed = [str(item).strip() for item in (payload.get("allowed_groups") or []) if str(item).strip()]
        known_groups = {group.id for group in store.list_groups()}
        unknown = [item for item in allowed if item not in known_groups]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown groups: {unknown}")
        return allowed

    def _validated_profile_payload(existing: AgentProfile | None, payload: dict[str, Any]) -> AgentProfile:
        config = get_config()
        merged: dict[str, Any] = existing.model_dump() if existing else {}
        merged.update(payload or {})
        merged["allowed_groups"] = _validated_allowed_groups(merged)
        permission_profile = str(merged.get("permission_profile") or "ask-first").strip() or "ask-first"
        if permission_profile not in config.permission_profiles:
            raise HTTPException(status_code=400, detail="Unknown permission profile")
        merged["permission_profile"] = permission_profile
        context_profile = str(merged.get("context_profile") or "").strip()
        if context_profile and context_profile not in config.context_profiles:
            raise HTTPException(status_code=400, detail="Unknown context profile")
        planner_context = str(merged.get("planner_context_profile") or "").strip()
        if planner_context and planner_context not in config.context_profiles:
            raise HTTPException(status_code=400, detail="Unknown planner context profile")
        visibility = str(merged.get("visibility") or "").strip()
        if visibility and visibility not in {"private", "group", "global"}:
            raise HTTPException(status_code=400, detail="Unknown visibility")
        return AgentProfile.model_validate(merged)

    def _require_admin(auth: Any) -> None:
        if not getattr(auth, "is_admin", False):
            raise HTTPException(status_code=403, detail="Admin required")

    def _profile_or_404(profile_name: str) -> AgentProfile:
        profile = get_config().agent_profiles.get(profile_name)
        if not profile:
            raise HTTPException(status_code=404, detail="Agent profile not found")
        return profile

    @router.get("/v1/profiles")
    def list_profiles(auth: Any = Depends(require_auth)) -> dict[str, Any]:
        config = get_config()
        profiles = {
            name: public_profile_payload(name, profile, auth, store=store)
            for name, profile in config.agent_profiles.items()
            if can_use_profile(profile, auth, store=store, profile_name=name) or getattr(auth, "is_admin", False)
        }
        return {
            "agent_profiles": profiles,
            "permission_profiles": {name: item.model_dump() for name, item in config.permission_profiles.items()},
            "workspaces": {name: item.model_dump() for name, item in config.workspaces.items()},
        }

    @router.get("/v1/agent-profiles")
    def list_agent_profiles(auth: Any = Depends(require_auth)) -> dict[str, Any]:
        config = get_config()
        return {
            name: public_profile_payload(name, profile, auth, store=store)
            for name, profile in config.agent_profiles.items()
            if can_use_profile(profile, auth, store=store, profile_name=name) or getattr(auth, "is_admin", False)
        }

    @router.get("/v1/agent-profiles/{profile_name}")
    def get_agent_profile(profile_name: str, auth: Any = Depends(require_auth)) -> dict[str, Any]:
        profile = _profile_or_404(profile_name)
        if not can_use_profile(profile, auth, store=store, profile_name=profile_name) and not getattr(auth, "is_admin", False):
            raise HTTPException(status_code=403, detail="You are not allowed to use this profile")
        return public_profile_payload(profile_name, profile, auth, store=store)

    @router.put("/v1/agent-profiles/{profile_name}")
    def upsert_agent_profile(profile_name: str, payload: dict[str, Any], auth: Any = Depends(require_auth)) -> dict[str, Any]:
        _require_admin(auth)
        config = get_config()
        existing = config.agent_profiles.get(profile_name)
        profile = _validated_profile_payload(existing, payload)
        config.agent_profiles[profile_name] = profile
        save_config(config)
        store.add_event(
            Event(
                session_id="system",
                type="agent_profile_saved",
                message=f"Profile saved: {profile_name}",
                data={"profile": profile_name, "allowed_groups": list(profile.allowed_groups or [])},
            )
        )
        return public_profile_payload(profile_name, profile, auth, store=store)

    @router.post("/v1/agent-profiles/{profile_name}/duplicate")
    def duplicate_agent_profile(profile_name: str, payload: dict[str, Any] | None = None, auth: Any = Depends(require_auth)) -> dict[str, Any]:
        _require_admin(auth)
        config = get_config()
        existing = _profile_or_404(profile_name)
        new_name = str((payload or {}).get("name") or "").strip()
        if not new_name:
            suffix = "-copy"
            candidate = f"{profile_name}{suffix}"
            idx = 2
            while candidate in config.agent_profiles:
                candidate = f"{profile_name}{suffix}-{idx}"
                idx += 1
            new_name = candidate
        if new_name in config.agent_profiles:
            raise HTTPException(status_code=400, detail=f"Agent profile already exists: {new_name}")
        duplicate = existing.model_copy(deep=True)
        if (payload or {}).get("display_name"):
            duplicate.display_name = str((payload or {}).get("display_name")).strip()
        config.agent_profiles[new_name] = duplicate
        save_config(config)
        store.add_event(Event(session_id="system", type="agent_profile_saved", message=f"Profile duplicated: {new_name}", data={"profile": new_name, "source_profile": profile_name}))
        return public_profile_payload(new_name, duplicate, auth)

    @router.delete("/v1/agent-profiles/{profile_name}")
    def delete_agent_profile(profile_name: str, auth: Any = Depends(require_auth)) -> dict[str, Any]:
        _require_admin(auth)
        config = get_config()
        if profile_name not in config.agent_profiles:
            raise HTTPException(status_code=404, detail="Agent profile not found")
        if profile_name == MAIN_PI_DEV_PROFILE:
            raise HTTPException(status_code=403, detail=f"Agent profile {MAIN_PI_DEV_PROFILE} is required and cannot be deleted")
        del config.agent_profiles[profile_name]
        save_config(config)
        store.add_event(Event(session_id="system", type="agent_profile_deleted", message=f"Agent profile deleted: {profile_name}"))
        return {"ok": True, "deleted": profile_name}

    return router
