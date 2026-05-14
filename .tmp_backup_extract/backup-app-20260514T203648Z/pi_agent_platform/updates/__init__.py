"""PAC self-update management - checks GitHub releases and applies updates."""
from __future__ import annotations

import json
import shutil
import subprocess
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.platform_home import ensure_pacp_layout, pacp_path

GITHUB_RELEASES_API = "https://api.github.com/repos/pac-labs/controller/releases"
GITHUB_REPO_URL = "https://github.com/pac-labs/controller"
PACKAGE_NAME = "pac-full.zip"


def _versiontuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.strip().lstrip("v").split(".") if p.isdigit())


def _version_is_newer(remote: str, current: str) -> bool:
    try:
        return _versiontuple(remote) > _versiontuple(current)
    except Exception:
        return False


def _fetch_github(url: str, timeout: int = 15) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "PAC/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def fetch_latest_release_metadata(current_version: str) -> dict[str, Any]:
    data = _fetch_github(GITHUB_RELEASES_API)
    if not data or not isinstance(data, list) or not data:
        return {
            "ok": False,
            "error": "Could not reach GitHub releases API",
            "current_version": current_version,
            "latest_version": None,
            "has_update": False,
            "release_url": GITHUB_REPO_URL,
        }

    latest = data[0]
    tag = latest.get("tag_name", "")
    version = tag.lstrip("v")
    has_update = _version_is_newer(version, current_version)

    assets = latest.get("assets") or []
    download_url = None
    for asset in assets:
        if asset.get("name") == PACKAGE_NAME:
            download_url = asset.get("browser_download_url")
            break

    body = (latest.get("body") or "").strip()
    changes: list[str] = []
    if body:
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("- ") or line.startswith("* "):
                changes.append(line[2:].strip())
            if len(changes) >= 10:
                break

    return {
        "ok": True,
        "current_version": current_version,
        "latest_version": version,
        "has_update": has_update,
        "release_url": latest.get("html_url") or GITHUB_REPO_URL,
        "download_url": download_url,
        "published_at": latest.get("published_at"),
        "tag": tag,
        "changes": changes[:10],
        "change_count": len(changes),
        "body": body[:1000] if body else None,
    }


def download_latest_release(download_url: str, dest: Path, timeout: int = 120) -> dict[str, Any]:
    req = urllib.request.Request(
        download_url,
        headers={"Accept": "application/octet-stream", "User-Agent": "PAC/1"},
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            dest.write_bytes(r.read())
        return {"ok": True, "path": str(dest), "size": dest.stat().st_size}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def apply_release_zip(zip_path: Path, apply_update: bool = True, restart_after_update: bool = True, previous_version: str | None = None) -> dict[str, Any]:
    """Apply a pac-full.zip to the local PAC app directory. Imports lazily to avoid circular refs.

    Before applying, generates a diff of local changes from the previously installed version
    (found via the extracted- dir matching previous_version) so the diff can be reapplied
    after the new version is installed. If the diff cannot be cleanly applied, the failure
    is reported to the caller so the UI can surface it to the user.
    """
    from fastapi import HTTPException
    from ..api.main import store, Event, _safe_zip_members, _find_package_root, _copy_package_tree, _pip_install_editable, _write_runtime_run_script, _schedule_local_restart

    home = ensure_pacp_layout()
    updates_dir = pacp_path("updates")
    uploads_dir = updates_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if not zip_path.exists():
        return {"ok": False, "error": f"Zip not found: {zip_path}"}

    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = _safe_zip_members(zf)
            zf.extractall(updates_dir / f"extracted-{stamp}")
    except zipfile.BadZipFile:
        return {"ok": False, "error": "Invalid zip file"}

    extract_dir = updates_dir / f"extracted-{stamp}"
    try:
        package_root = _find_package_root(extract_dir)
    except Exception as exc:
        return {"ok": False, "error": f"Could not find package root: {exc}"}

    # Read new version from the extracted package
    new_version = "unknown"
    vfile = package_root / "VERSION"
    if vfile.exists():
        new_version = vfile.read_text().strip()

    if not apply_update:
        store.add_event(Event(
            session_id="system", type="package_uploaded",
            message=f"Release zip validated: {zip_path.name}",
            data={"zip_path": str(zip_path), "package_root": str(package_root)},
        ))
        return {"ok": True, "status": "validated", "package_root": str(package_root), "new_version": new_version}

    app_dir = Path(__file__).resolve().parents[2] / "app"

    # Determine previous version: use provided arg, or read from current app VERSION
    prev_version = previous_version
    if not prev_version:
        vfile_current = app_dir / "VERSION"
        if vfile_current.exists():
            prev_version = vfile_current.read_text().strip()

    diff_result: dict[str, Any] = {"skipped": True}
    diff_applied_result: dict[str, Any] = {"skipped": True}

    # Step 1: Generate diff of local changes from previous version's extracted source
    if prev_version and prev_version != "unknown":
        try:
            from .diff_utils import find_extracted_for_version, generate_diff, get_diff_file
            old_extracted = find_extracted_for_version(updates_dir, prev_version)
            if old_extracted and old_extracted.exists():
                diff_path = get_diff_file(updates_dir, prev_version, new_version)
                diff_result = generate_diff(old_extracted, app_dir, diff_path)
                # Save the diff zip alongside backups for recovery
                if diff_result.get("ok") and diff_path.exists():
                    diff_zip_dest = updates_dir / f"local-patch-from-{prev_version}-to-{new_version}.zip"
                    with zipfile.ZipFile(diff_zip_dest, "w", zipfile.ZIP_DEFLATED) as zf:
                        zf.write(diff_path, arcname=diff_path.name)
        except Exception as exc:
            diff_result = {"skipped": False, "ok": False, "error": str(exc)}

    backup_dir = updates_dir / f"backup-app-{stamp}"
    if app_dir.exists():
        shutil.copytree(app_dir, backup_dir, ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc"))

    # Step 2: Copy new package files over current app
    copied = _copy_package_tree(package_root, app_dir)
    pip_result = _pip_install_editable(app_dir)
    run_script_result = _write_runtime_run_script(app_dir)

    # Step 3: Reapply the local diff on top of the newly installed version
    if diff_result.get("ok") and diff_result.get("diff_path"):
        try:
            from .diff_utils import apply_diff
            diff_applied_result = apply_diff(Path(diff_result["diff_path"]), app_dir)
        except Exception as exc:
            diff_applied_result = {"ok": False, "error": str(exc)}

    marker = pacp_path("run", "restart-required")
    marker.write_text(
        f"PAC update applied at {stamp}\nsource={zip_path}\nbackup={backup_dir}\n",
        encoding="utf-8",
    )

    store.add_event(Event(
        session_id="system", type="package_applied",
        message=f"GitHub release applied: {zip_path.name}. Restart required.",
        data={
            "zip_path": str(zip_path),
            "backup_dir": str(backup_dir),
            "copied": copied,
            "previous_version": prev_version,
            "new_version": new_version,
            "local_diff": diff_result,
            "diff_applied": diff_applied_result,
        },
    ))

    status = "installed_restarting" if restart_after_update else "installed_restart_required"
    if restart_after_update:
        _schedule_local_restart(f"PAC local restart after GitHub release: {zip_path.name}")

    return {
        "ok": True,
        "status": status,
        "backup_dir": str(backup_dir),
        "copied": copied,
        "pip": pip_result,
        "run_script": run_script_result,
        "restart_required": True,
        "restart_scheduled": restart_after_update,
        "previous_version": prev_version,
        "new_version": new_version,
        "local_diff": diff_result,
        "diff_applied": diff_applied_result,
    }