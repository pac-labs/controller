"""Diff utilities for preserving local modifications across PAC updates.

Workflow:
  1. BEFORE applying a new update - generate a diff of local changes since the
     last applied version (compares extracted/{last_version}/ to current app/).
  2. AFTER applying the new update - attempt to reapply that diff on top.
  3. If the diff fails to apply cleanly, surface the conflict details so the
     user can resolve manually.

Diff files are stored in updates/local-patches/ as unified patches.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

# Files/dirs to ALWAYS ignore when generating diffs - these are runtime state
# that should not be patched across versions.
_IGNORE_PATTERNS = [
    ".venv",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".git",
    ".pac",
    "state.db",
    "state.db-shm",
    "state.db-wal",
    "cache",
    "logs",
    "sessions",
    "run",
    "config",
    "updates",
    "pi-agent-artifacts",
]


def get_installed_version(app_dir: Path) -> str:
    """Read the VERSION file from the currently running app directory."""
    v = app_dir / "VERSION"
    if v.exists():
        return v.read_text().strip()
    return "unknown"


def find_extracted_for_version(updates_dir: Path, version: str) -> Path | None:
    """Find the extracted- directory matching the given version.

    If multiple exist, returns the most recent (sorted by name, which is timestamped).
    Returns None if no match found.
    """
    if not updates_dir.exists():
        return None
    candidates = []
    for d in sorted(updates_dir.iterdir()):
        if not (d.is_dir() and d.name.startswith("extracted-")):
            continue
        vf = d / "VERSION"
        if vf.exists() and vf.read_text().strip() == version:
            candidates.append(d)
    if not candidates:
        return None
    return candidates[-1]


def generate_diff(old_dir: Path, new_dir: Path, output_path: Path) -> dict[str, Any]:
    """Generate a unified diff of all differences from old_dir to new_dir.

    Only compares files that exist in old_dir (for accurate added/deleted detection).
    Returns dict with ok, diff_path, stats (files_changed, files_added, files_removed).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    exclude_args: list[str] = []
    for pat in _IGNORE_PATTERNS:
        exclude_args.extend(["--exclude", pat])

    proc = subprocess.run(
        ["diff", "-ruN"] + exclude_args + [str(old_dir) + "/", str(new_dir) + "/"],
        capture_output=True,
        text=True,
        timeout=180,
    )

    files_changed: set[str] = set()
    files_added: set[str] = set()
    files_removed: set[str] = set()

    for line in proc.stdout.splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            parts = line[4:].split("\t", 1)[0].strip()
            fname = parts.replace("a/", "").replace("b/", "").split(" ")[0]
            if not fname or fname in ("dev/null", "/dev/null"):
                continue
            if line.startswith("--- "):
                files_removed.add(fname)
            elif line.startswith("+++ "):
                if fname in files_removed:
                    files_changed.add(fname)
                    files_removed.discard(fname)
                else:
                    files_added.add(fname)

    # Filter out ignore-pattern noise lines
    filtered_lines = []
    skip_tokens = {".venv", "__pycache__", ".git", "state.db", "updates/"}
    for line in proc.stdout.splitlines(keepends=True):
        if not any(tok in line for tok in skip_tokens):
            filtered_lines.append(line)

    filtered_output = "".join(filtered_lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(filtered_output)

    return {
        "ok": True,
        "diff_path": str(output_path),
        "stats": {
            "files_changed": len(files_changed),
            "files_added": len(files_added),
            "files_removed": len(files_removed),
            "total_lines": len(filtered_output.splitlines()),
        },
        "changed_files": sorted(files_changed)[:30],
        "added_files": sorted(files_added)[:30],
        "removed_files": sorted(files_removed)[:30],
    }


def apply_diff(diff_path: Path, target_dir: Path) -> dict[str, Any]:
    """Apply a unified diff patch to target_dir.

    Uses patch --dry-run first to detect errors, then applies for real.
    Returns dict with ok, applied_count, failed_files.
    """
    if not diff_path.exists() or not diff_path.read_text(errors="ignore").strip():
        return {"ok": True, "applied_count": 0, "failed_files": [], "skipped": True}

    # Dry run first with fuzz tolerance
    dry = subprocess.run(
        ["patch", "-p1", "--dry-run", "--fuzz=3", "-i", str(diff_path)],
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        timeout=120,
    )

    if dry.returncode != 0:
        failed = [
            line.strip()
            for line in dry.stderr.splitlines()
            if any(kw in line.lower() for kw in ("patching file", "failed", "cannot apply"))
        ]
        return {
            "ok": False,
            "applied_count": 0,
            "failed_files": failed[:20],
            "full_stderr": dry.stderr[:4000],
            "dry_run": True,
        }

    # Apply for real
    real = subprocess.run(
        ["patch", "-p1", "--fuzz=3", "-i", str(diff_path)],
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        timeout=120,
    )

    if real.returncode != 0:
        failed = [
            line.strip()
            for line in real.stderr.splitlines()
            if any(kw in line.lower() for kw in ("patching file", "failed", "cannot apply"))
        ]
        return {
            "ok": False,
            "applied_count": 0,
            "failed_files": failed[:20],
            "full_stderr": real.stderr[:4000],
            "dry_run": False,
        }

    patched = real.stdout.count("patching file")
    return {
        "ok": True,
        "applied_count": patched,
        "failed_files": [],
        "full_output": (real.stdout + real.stderr)[:3000],
    }


def get_diff_file(updates_dir: Path, from_version: str, to_version: str) -> Path:
    """Path where the patch file for this version transition should live."""
    pdir = updates_dir / "local-patches"
    pdir.mkdir(parents=True, exist_ok=True)
    return pdir / f"from-{from_version}-to-{to_version}.patch"


def diff_summary(diff_path: Path) -> dict[str, Any]:
    """Human-readable summary of a diff file without applying it."""
    if not diff_path.exists():
        return {"ok": False, "error": "diff not found"}

    content = diff_path.read_text(encoding="utf-8", errors="replace")
    if not content.strip():
        return {"ok": True, "size_bytes": 0, "files": [], "empty": True}

    files = set()
    for line in content.splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            parts = line[4:].split("\t", 1)[0].strip()
            fname = parts.replace("a/", "").replace("b/", "").split(" ")[0]
            if fname and fname not in ("dev/null", "/dev/null"):
                files.add(fname)

    return {
        "ok": True,
        "size_bytes": len(content),
        "size_kb": len(content) / 1024,
        "files": sorted(files)[:50],
        "total_files": len(files),
        "empty": False,
    }


def build_diff_between_versions(updates_dir: Path, from_version: str, to_version: str, app_dir: Path) -> dict[str, Any]:
    """Convenience: build a diff patch from from_version extracted dir to the current app dir."""
    old_dir = find_extracted_for_version(updates_dir, from_version)
    if not old_dir:
        return {"ok": False, "error": f"Could not find extracted source for version {from_version}"}

    diff_path = get_diff_file(updates_dir, from_version, to_version)
    return generate_diff(old_dir, app_dir, diff_path)