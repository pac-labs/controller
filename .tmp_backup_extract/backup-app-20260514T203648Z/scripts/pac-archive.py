#!/usr/bin/env python3
"""Archive the current ~/.pacp/app as an immutable versioned zip.

Usage:
  python3 pac-archive.py [--version X.Y.Z]

Output:
  ~/.pacp/archives/v{X.Y.Z}.zip  — complete source snapshot
  ~/.pacp/archives/v{X.Y.Z}.json — metadata (version, timestamp, size, checksum)
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

APPDIR = Path.home() / ".pacp" / "app"
ARCHIVEDIR = Path.home() / ".pacp" / "archives"


def get_local_version() -> str:
    v = (APPDIR / "VERSION").read_text(encoding="utf-8").strip()
    return v


def get_git_revision() -> str:
    """Return the current git revision if ~/.pacp/app is a git repo, else ''."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=APPDIR, text=True, capture_output=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


EXCLUDE_NAMES = {
    ".venv", "__pycache__", ".git", ".gitignore",
    "state.db", "state.db-shm", "state.db-wal",
    "pi-agent-artifacts", "sessions", "logs",
}
EXCLUDE_EXTENSIONS = {".pyc", ".pyo", ".so", ".egg-info"}
EXCLUDE_PREFIXES = ("config/",)


def should_exclude(path: str) -> bool:
    parts = path.split("/")
    for part in parts:
        if part in EXCLUDE_NAMES:
            return True
        if any(part.endswith(ext) for ext in EXCLUDE_EXTENSIONS):
            return True
    for prefix in EXCLUDE_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def build_archive(version: str):
    ARCHIVEDIR.mkdir(parents=True, exist_ok=True)
    zip_path = ARCHIVEDIR / f"v{version}.zip"
    json_path = ARCHIVEDIR / f"v{version}.json"

    if zip_path.exists():
        print(f"[archive] {zip_path} already exists — skipping")
        meta = json.loads(json_path.read_text()) if json_path.exists() else {}
        return zip_path, meta

    print(f"[archive] Building archive for v{version}...")
    print(f"[archive] Source: {APPDIR}")
    print(f"[archive] Output: {zip_path}")

    files = []
    for item in APPDIR.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(APPDIR).as_posix()
        if should_exclude(rel):
            continue
        files.append((rel, item))

    print(f"[archive] {len(files)} files to archive")

    fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)

    total_size = 0
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, abspath in sorted(files):
            zf.write(abspath, arcname=rel)
            total_size += abspath.stat().st_size

    sha256 = hashlib.sha256()
    with open(tmp_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)

    shutil.move(tmp_path, zip_path)

    git_rev = get_git_revision()
    meta = {
        "version": version,
        "archived_at": subprocess.run(
            ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True, capture_output=True
        ).stdout.strip(),
        "git_revision": git_rev,
        "file_count": len(files),
        "total_bytes": total_size,
        "checksum_sha256": sha256.hexdigest(),
        "archive_path": str(zip_path),
    }

    json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[archive] Done: {zip_path} ({total_size:,} bytes, sha256={sha256.hexdigest()[:16]}...)")
    return zip_path, meta


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive the current PAC app source")
    parser.add_argument("--version", help="Version string (default: read from VERSION file)")
    args = parser.parse_args()

    version = args.version or get_local_version()
    if not version:
        print("[archive] ERROR: Could not determine version. Is VERSION file present?", file=sys.stderr)
        return 1

    try:
        zip_path, meta = build_archive(version)
        print(f"[archive] Archived: v{meta['version']} at {meta['archived_at']}")
        print(f"[archive] {meta['file_count']} files, {meta['total_bytes']:,} bytes")
        return 0
    except Exception as exc:
        print(f"[archive] ERROR: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
