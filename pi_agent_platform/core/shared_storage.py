from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import now_utc


class SharedStorage(BaseModel):
    id: str
    name: str
    description: str | None = None
    driver: Literal["nfs", "smb", "cifs", "sshfs", "object", "custom"] = "nfs"
    network_path: str | None = None
    controller_path: str | None = None
    mount_path: str = "/workspace"
    endpoint_selector: str | None = None
    endpoint_ids: list[str] = Field(default_factory=list)
    writable: bool = True
    default_subpath: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Any = Field(default_factory=now_utc)
    updated_at: Any = Field(default_factory=now_utc)

    def touch(self) -> None:
        self.updated_at = now_utc()


def controller_storage_path(storage: SharedStorage, subpath: str | None = None) -> str | None:
    root = str(storage.controller_path or "").strip()
    if not root:
        return None
    target = Path(root).expanduser()
    leaf = str(subpath or storage.default_subpath or "").strip().strip("/\\")
    if leaf:
        target = target / leaf
    return str(target)


def shared_storage_binding(storage: SharedStorage, subpath: str | None = None, mount_path: str | None = None) -> dict[str, Any]:
    return {
        "shared_storage_id": storage.id,
        "shared_storage_name": storage.name,
        "shared_storage_driver": storage.driver,
        "shared_storage_network_path": storage.network_path,
        "shared_storage_controller_path": controller_storage_path(storage, subpath),
        "shared_storage_mount_path": str(mount_path or storage.mount_path or "/workspace").strip() or "/workspace",
        "shared_storage_subpath": str(subpath or storage.default_subpath or "").strip() or None,
        "shared_storage_writable": bool(storage.writable),
        "shared_storage_endpoint_selector": storage.endpoint_selector,
        "shared_storage_endpoint_ids": list(storage.endpoint_ids or []),
    }


def public_shared_storage(storage: SharedStorage) -> dict[str, Any]:
    def _json_time(value: Any) -> str | None:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    return {
        "id": storage.id,
        "name": storage.name,
        "description": storage.description,
        "driver": storage.driver,
        "network_path": storage.network_path,
        "controller_path": storage.controller_path,
        "mount_path": storage.mount_path,
        "endpoint_selector": storage.endpoint_selector,
        "endpoint_ids": list(storage.endpoint_ids or []),
        "writable": bool(storage.writable),
        "default_subpath": storage.default_subpath,
        "metadata": storage.metadata or {},
        "created_at": _json_time(storage.created_at),
        "updated_at": _json_time(storage.updated_at),
    }
