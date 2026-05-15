from __future__ import annotations

import difflib
import hashlib
import json
import subprocess
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TRACKED_ROOTS = {
    "README.md",
    "requirements.txt",
    "pyproject.toml",
    ".gitignore",
    "pi_agent_platform",
    "config",
    "scripts",
    "deploy",
    "containers",
    "docs",
    "tests",
    "vscode-extension",
    "binaries",
    "VERSION",
    "VERSION_CURRENT.md",
    "FILES.txt",
    "MANIFEST.json",
    "docs-zed-mcp-example.json",
    "install.sh",
    "mcp",
}
IGNORE_PARTS = {"__pycache__", ".venv", ".git", "logs", "sessions", "cache", "run", "updates", "pi-agent-artifacts"}
IGNORE_SUFFIXES = {".pyc", ".pyo", ".db", ".wal", ".shm"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tracked_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for entry in TRACKED_ROOTS:
        target = root / entry
        if not target.exists():
            continue
        if target.is_file():
            files[entry] = target
            continue
        for item in target.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(root).as_posix()
            if any(part in IGNORE_PARTS for part in item.parts):
                continue
            if item.suffix.lower() in IGNORE_SUFFIXES:
                continue
            files[rel] = item
    return files


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None
    except Exception:
        return None


def build_backup_archive(app_dir: Path, backup_tar_gz: Path) -> dict[str, Any]:
    backup_tar_gz.parent.mkdir(parents=True, exist_ok=True)
    tracked = _tracked_files(app_dir)
    with tarfile.open(backup_tar_gz, "w:gz") as archive:
        for rel, path in sorted(tracked.items()):
            archive.add(path, arcname=path.relative_to(app_dir).as_posix())
    digest = hashlib.sha256(backup_tar_gz.read_bytes()).hexdigest()
    return {
        "archive_path": str(backup_tar_gz),
        "file_count": len(tracked),
        "checksum_sha256": digest,
        "created_at": _utc_now(),
    }


def compare_trees(installed_root: Path, incoming_root: Path, diff_path: Path, summary_path: Path) -> dict[str, Any]:
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    installed = _tracked_files(installed_root)
    incoming = _tracked_files(incoming_root)
    all_paths = sorted(set(installed) | set(incoming))
    diff_chunks: list[str] = []
    added: list[str] = []
    removed: list[str] = []
    modified: list[str] = []
    for rel in all_paths:
        left = installed.get(rel)
        right = incoming.get(rel)
        if left and not right:
            removed.append(rel)
        elif right and not left:
            added.append(rel)
        else:
            assert left and right
            left_text = _read_text(left)
            right_text = _read_text(right)
            if left_text is None or right_text is None:
                if left.read_bytes() != right.read_bytes():
                    modified.append(rel)
                continue
            if left_text != right_text:
                modified.append(rel)
                diff_chunks.extend(
                    difflib.unified_diff(
                        right_text.splitlines(),
                        left_text.splitlines(),
                        fromfile=f"a/{rel}",
                        tofile=f"b/{rel}",
                        lineterm="",
                    )
                )
                diff_chunks.append("")
    diff_path.write_text("\n".join(diff_chunks).rstrip() + ("\n" if diff_chunks else ""), encoding="utf-8")
    summary = {
        "generated_at": _utc_now(),
        "installed_root": str(installed_root),
        "incoming_root": str(incoming_root),
        "added": added,
        "removed": removed,
        "modified": modified,
        "file_count": {"added": len(added), "removed": len(removed), "modified": len(modified)},
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _read_remote_text(base_url: str, rel_path: str) -> str | None:
    url = f"{base_url.rstrip('/')}/{rel_path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PAC-local-diff/1"})
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def generate_local_diff(app_dir: Path, version: str, out_dir: Path, github_raw_base: str = "https://raw.githubusercontent.com/pac-labs/controller/main") -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    diff_path = out_dir / f"v{version}.diff"

    has_git = (app_dir / ".git").exists()
    if has_git:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", "origin/main"],
            cwd=app_dir,
            text=True,
            capture_output=True,
            check=False,
        )
        has_git = result.returncode == 0

    if has_git:
        result = subprocess.run(
            ["git", "diff", "--binary", "--no-color", "origin/main", "--", "."],
            cwd=app_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        diff_text = result.stdout or ""
    else:
        diff_lines: list[str] = []
        tracked = _tracked_files(app_dir)
        for rel, local_path in sorted(tracked.items()):
            local_text = _read_text(local_path)
            if local_text is None:
                continue
            remote_text = _read_remote_text(github_raw_base, rel)
            if remote_text is None:
                diff_lines.append(f"diff --git a/{rel} b/{rel}")
                diff_lines.extend(
                    difflib.unified_diff(
                        [],
                        local_text.splitlines(),
                        fromfile=f"a/{rel}",
                        tofile=f"b/{rel}",
                        lineterm="",
                    )
                )
                diff_lines.append("")
                continue
            if local_text == remote_text:
                continue
            diff_lines.append(f"diff --git a/{rel} b/{rel}")
            diff_lines.extend(
                difflib.unified_diff(
                    remote_text.splitlines(),
                    local_text.splitlines(),
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                    lineterm="",
                )
            )
            diff_lines.append("")
        diff_text = "\n".join(diff_lines).rstrip() + ("\n" if diff_lines else "")

    if not diff_text.strip():
        return {"ok": True, "status": "no_diff", "message": "No differences found.", "diff_path": None}

    diff_path.write_text(diff_text, encoding="utf-8")
    return {
        "ok": True,
        "status": "written",
        "version": version,
        "diff_path": str(diff_path),
        "size": diff_path.stat().st_size,
        "generated_at": _utc_now(),
    }


def list_generated_diffs(out_dir: Path) -> list[dict[str, Any]]:
    if not out_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(out_dir.glob("v*.diff"), key=lambda item: item.stat().st_mtime, reverse=True):
        version = path.stem[1:] if path.stem.startswith("v") else path.stem
        stat = path.stat()
        items.append(
            {
                "version": version,
                "filename": path.name,
                "path": str(path),
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return items
