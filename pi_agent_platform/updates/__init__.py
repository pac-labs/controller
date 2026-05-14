from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

GITHUB_REPO = os.environ.get("PAC_GITHUB_REPO", "pac-labs/controller").strip() or "pac-labs/controller"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_REPO}"
PACKAGE_NAME = "pac-full.zip"


def _version_tuple(value: str | None) -> tuple[int, ...]:
    parts = []
    for token in str(value or "").strip().lstrip("v").split("."):
        match = re.match(r"^(\d+)", token)
        parts.append(int(match.group(1)) if match else 0)
    return tuple(parts or [0])


def _fetch_json(url: str, timeout: int = 15) -> dict[str, Any] | None:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "PAC/updates",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _body_changes(body: str) -> list[str]:
    changes: list[str] = []
    for raw in str(body or "").splitlines():
        line = raw.strip()
        if line.startswith("- ") or line.startswith("* "):
            changes.append(line[2:].strip())
        if len(changes) >= 12:
            break
    return changes


def fetch_latest_release_metadata(current_version: str) -> dict[str, Any]:
    release = _fetch_json(GITHUB_RELEASES_API)
    if not release:
        return {
            "ok": False,
            "error": "Could not reach the PAC release feed",
            "current_version": current_version,
            "latest_version": None,
            "has_update": False,
            "release_url": GITHUB_REPO_URL,
        }
    tag = str(release.get("tag_name") or "").strip()
    latest_version = tag.lstrip("v") or None
    body = str(release.get("body") or "").strip()
    download_url = None
    for asset in release.get("assets") or []:
        if str(asset.get("name") or "") == PACKAGE_NAME:
            download_url = asset.get("browser_download_url")
            break
    return {
        "ok": True,
        "current_version": current_version,
        "latest_version": latest_version,
        "has_update": bool(latest_version and _version_tuple(latest_version) > _version_tuple(current_version)),
        "release_url": release.get("html_url") or GITHUB_REPO_URL,
        "download_url": download_url,
        "published_at": release.get("published_at"),
        "tag": tag or None,
        "body": body[:4000] if body else None,
        "changes": _body_changes(body),
        "change_count": len(_body_changes(body)),
        "repo": GITHUB_REPO,
    }


def download_release_package(download_url: str, destination: Path, timeout: int = 180) -> dict[str, Any]:
    request = urllib.request.Request(
        str(download_url),
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "PAC/updates",
        },
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            destination.write_bytes(response.read())
        return {"ok": True, "path": str(destination), "size": destination.stat().st_size}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
