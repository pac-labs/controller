from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .platform_home import pacp_path

SAFE_CONTAINER_PREFIXES = ("pi-agent-job-", "pac-mcp-builder", "pac-builder-")


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, p.stdout, p.stderr
    except Exception as exc:
        return 999, "", str(exc)


def _parse_container_json(raw: str) -> list[dict[str, Any]]:
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return [x for x in parsed if isinstance(x, dict)]
    except Exception:
        pass
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except Exception:
            continue
    return rows


def _container_names(item: dict[str, Any]) -> list[str]:
    names = item.get("Names") or item.get("names") or item.get("NamesList") or item.get("Name") or item.get("name")
    if isinstance(names, list):
        return [str(x).lstrip("/") for x in names]
    if isinstance(names, str):
        # Docker --format json uses a single Names field; podman often uses a list.
        return [x.strip().lstrip("/") for x in names.replace(",", " ").split() if x.strip()]
    return []


def _container_id(item: dict[str, Any]) -> str | None:
    for key in ("ID", "Id", "id", "ContainerID"):
        value = item.get(key)
        if value:
            return str(value)
    return None


def _is_running(item: dict[str, Any]) -> bool:
    state = str(item.get("State") or item.get("state") or "").lower()
    status = str(item.get("Status") or item.get("status") or "").lower()
    return state == "running" or status.startswith("up ") or "running" in status


def _safe_container(item: dict[str, Any]) -> bool:
    names = _container_names(item)
    return any(name.startswith(SAFE_CONTAINER_PREFIXES) for name in names)


def _remove_old_path(path: Path, cutoff: float, dry_run: bool) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        if path.stat().st_mtime > cutoff:
            return None
        info = {"path": str(path), "type": "directory" if path.is_dir() else "file", "removed": not dry_run}
        if not dry_run:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        return info
    except Exception as exc:
        return {"path": str(path), "error": str(exc), "removed": False}


def run_endpoint_maintenance(
    *,
    max_age_hours: int = 24,
    dry_run: bool = False,
    remove_containers: bool = True,
    remove_workspaces: bool = True,
    remove_temp_artifacts: bool = True,
    prune_images: bool = False,
) -> dict[str, Any]:
    """Clean old PAC endpoint clutter without touching unrelated workloads.

    Safety rules:
    - Only stopped containers with PAC-created names are removed.
    - Workspaces are removed only from ~/.pacp/runner/workspaces and only when older than max_age_hours.
    - Image pruning is opt-in and disabled by default.
    """
    cutoff = time.time() - max(1, int(max_age_hours)) * 3600
    result: dict[str, Any] = {
        "dry_run": dry_run,
        "max_age_hours": max_age_hours,
        "containers": [],
        "workspaces": [],
        "temp_artifacts": [],
        "image_prune": [],
        "summary": {"containers_removed": 0, "workspaces_removed": 0, "temp_artifacts_removed": 0},
    }

    if remove_containers:
        for runtime in ("podman", "docker"):
            if not shutil.which(runtime):
                continue
            code, out, err = _run([runtime, "ps", "-a", "--format", "json"], timeout=20)
            if code != 0:
                result["containers"].append({"runtime": runtime, "error": err.strip() or out.strip()})
                continue
            for item in _parse_container_json(out):
                names = _container_names(item)
                cid = _container_id(item)
                if not cid or not _safe_container(item) or _is_running(item):
                    continue
                entry = {"runtime": runtime, "id": cid, "names": names, "removed": False}
                if not dry_run:
                    rm_code, rm_out, rm_err = _run([runtime, "rm", cid], timeout=30)
                    entry["removed"] = rm_code == 0
                    if rm_code != 0:
                        entry["error"] = rm_err.strip() or rm_out.strip()
                    else:
                        result["summary"]["containers_removed"] += 1
                result["containers"].append(entry)

    if remove_workspaces:
        workspace_root = pacp_path("runner", "workspaces")
        if workspace_root.exists():
            for child in workspace_root.iterdir():
                removed = _remove_old_path(child, cutoff, dry_run)
                if removed:
                    result["workspaces"].append(removed)
                    if removed.get("removed"):
                        result["summary"]["workspaces_removed"] += 1

    if remove_temp_artifacts:
        for path in Path("/tmp").glob("pi-agent-artifacts-*.tar.gz"):
            removed = _remove_old_path(path, cutoff, dry_run)
            if removed:
                result["temp_artifacts"].append(removed)
                if removed.get("removed"):
                    result["summary"]["temp_artifacts_removed"] += 1

    if prune_images:
        for runtime in ("podman", "docker"):
            if not shutil.which(runtime):
                continue
            if dry_run:
                result["image_prune"].append({"runtime": runtime, "skipped": "dry_run"})
                continue
            code, out, err = _run([runtime, "image", "prune", "-f"], timeout=120)
            result["image_prune"].append({"runtime": runtime, "ok": code == 0, "output": (out or err).strip()[-4000:]})

    return result
