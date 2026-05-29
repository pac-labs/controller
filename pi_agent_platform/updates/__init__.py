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
GITHUB_COMPARE_API = f"https://api.github.com/repos/{GITHUB_REPO}/compare"
PACKAGE_NAME = "pac-full.zip"
RELEASE_ASSET_NAMES = {
    "full": "pac-full.zip",
    "patch": "pac-patch.zip",
    "packages_seed": "pac-packages-seed.zip",
    "release_binaries": "pac-binaries.zip",
    "release_binaries_manifest": "RELEASE_BINARIES.json",
    "release_manifest": "PAC_RELEASE_MANIFEST.json",
    "update_diff": "PAC_UPDATE_DIFF.diff",
}


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


def _compare_changes(current_version: str | None, latest_version: str | None) -> list[str]:
    current = str(current_version or "").strip().lstrip("v")
    latest = str(latest_version or "").strip().lstrip("v")
    if not current or not latest or _version_tuple(latest) <= _version_tuple(current):
        return []
    compare = _fetch_json(f"{GITHUB_COMPARE_API}/v{current}...v{latest}")
    if not compare:
        return []
    changes: list[str] = []
    for commit in compare.get("commits") or []:
        message = str(((commit.get("commit") or {}).get("message")) or "").strip()
        title = message.splitlines()[0].strip()
        if not title:
            continue
        if title not in changes:
            changes.append(title)
        if len(changes) >= 20:
            break
    return changes


def _asset_record(asset: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    return {
        "name": name or asset.get("name"),
        "download_url": asset.get("browser_download_url"),
        "size": asset.get("size"),
        "content_type": asset.get("content_type"),
        "updated_at": asset.get("updated_at"),
    }


def _asset_map(release: dict[str, Any]) -> dict[str, Any]:
    assets: dict[str, Any] = {}
    by_name = {str(asset.get("name") or ""): asset for asset in release.get("assets") or [] if isinstance(asset, dict)}
    for key, name in RELEASE_ASSET_NAMES.items():
        asset = by_name.get(name)
        if not asset:
            continue
        assets[key] = _asset_record(asset, name)
    for name, asset in by_name.items():
        if name.startswith("pac-endpoint-") or name.startswith("pacctl-"):
            assets[f"binary:{name}"] = _asset_record(asset, name)
    return assets


def fetch_latest_release_assets() -> dict[str, Any]:
    release = _fetch_json(GITHUB_RELEASES_API)
    if not release:
        return {"ok": False, "error": "Could not reach the PAC release feed", "repo": GITHUB_REPO, "assets": {}}
    return {
        "ok": True,
        "repo": GITHUB_REPO,
        "tag": release.get("tag_name"),
        "version": str(release.get("tag_name") or "").lstrip("v") or None,
        "release_url": release.get("html_url") or GITHUB_REPO_URL,
        "published_at": release.get("published_at"),
        "assets": _asset_map(release),
    }


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
    body_changes = _body_changes(body)
    compare_changes = _compare_changes(current_version, latest_version)
    assets = _asset_map(release)
    download_url = (assets.get("full") or {}).get("download_url")
    return {
        "ok": True,
        "current_version": current_version,
        "latest_version": latest_version,
        "has_update": bool(latest_version and _version_tuple(latest_version) > _version_tuple(current_version)),
        "release_url": release.get("html_url") or GITHUB_REPO_URL,
        "download_url": download_url,
        "assets": assets,
        "published_at": release.get("published_at"),
        "tag": tag or None,
        "body": body[:20000] if body else None,
        "changes": body_changes,
        "change_count": len(body_changes),
        "compare_changes": compare_changes,
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


def download_release_asset(asset_key: str, destination: Path, timeout: int = 180) -> dict[str, Any]:
    assets = fetch_latest_release_assets()
    if not assets.get("ok"):
        return {"ok": False, "status": "release_feed_unavailable", "error": assets.get("error"), "asset_key": asset_key}
    asset = (assets.get("assets") or {}).get(asset_key)
    download_url = str((asset or {}).get("download_url") or "").strip()
    if not download_url:
        return {"ok": False, "status": "asset_missing", "error": f"Release asset is missing: {asset_key}", "asset_key": asset_key}
    result = download_release_package(download_url, destination, timeout=timeout)
    result.update({"asset_key": asset_key, "asset": asset, "release": {"tag": assets.get("tag"), "version": assets.get("version"), "release_url": assets.get("release_url")}})
    return result
