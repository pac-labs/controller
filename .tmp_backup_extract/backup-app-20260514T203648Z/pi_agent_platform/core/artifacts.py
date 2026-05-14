from __future__ import annotations

import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def artifacts_root(data_dir: str | Path) -> Path:
    root = Path(data_dir) / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def task_artifact_dir(data_dir: str | Path, session_id: str, task_id: str | None = None) -> Path:
    path = artifacts_root(data_dir) / session_id / (task_id or "session")
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_artifact_path(base: Path, name: str) -> Path:
    clean = name.strip().replace("\\", "/").lstrip("/")
    target = (base / clean).resolve()
    if base.resolve() != target and base.resolve() not in target.parents:
        raise ValueError("artifact path escapes artifact directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def write_artifact(data_dir: str | Path, session_id: str, task_id: str | None, name: str, data: bytes) -> dict[str, Any]:
    base = task_artifact_dir(data_dir, session_id, task_id)
    target = safe_artifact_path(base, name)
    target.write_bytes(data)
    meta = {
        "id": f"art_{uuid4().hex[:12]}",
        "session_id": session_id,
        "task_id": task_id,
        "name": name,
        "size": len(data),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (target.with_name(target.name + ".meta.json")).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def list_artifacts(data_dir: str | Path, session_id: str | None = None, task_id: str | None = None) -> list[dict[str, Any]]:
    root = artifacts_root(data_dir)
    if session_id:
        root = root / session_id
        if task_id:
            root = root / task_id
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in root.rglob("*.meta.json"):
        try:
            meta = json.loads(path.read_text())
        except Exception:
            continue
        artifact_path = path.with_name(path.name.removesuffix(".meta.json"))
        if artifact_path.exists():
            meta["size"] = artifact_path.stat().st_size
            meta["download_path"] = f"/v1/artifacts/{meta['session_id']}/{meta.get('task_id') or 'session'}/{meta['name']}"
            out.append(meta)
    return sorted(out, key=lambda x: x.get("created_at", ""), reverse=True)


def create_workspace_artifact_bundle(data_dir: str | Path, session_id: str, task_id: str | None, workspace: str | Path, include_dirs: list[str] | None = None) -> dict[str, Any] | None:
    workspace = Path(workspace)
    include_dirs = include_dirs or ["artifacts", "pi-agent-artifacts"]
    candidates = [workspace / p for p in include_dirs if (workspace / p).exists()]
    if not candidates:
        return None
    base = task_artifact_dir(data_dir, session_id, task_id)
    bundle = base / "workspace-artifacts.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        for candidate in candidates:
            tar.add(candidate, arcname=candidate.name)
    return write_artifact(data_dir, session_id, task_id, "workspace-artifacts.tar.gz", bundle.read_bytes())
