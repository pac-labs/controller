#!/usr/bin/env python3
"""Generate a diff between the local ~/.pacp/app and the online main branch.

Usage:
  python generate-local-diff.py [--version X.Y.Z] [--output DIR]

Output:
  .pac/diffs/vX.Y.Z.diff — a git-style diff that can be submitted to GitHub
                           to trigger a PAC release via the pac-diff-release workflow.
"""
from __future__ import annotations

import argparse
import difflib
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

APPDIR = Path(__file__).resolve().parents[1]  # = ~/.pacp/app
GITHUB_RAW = "https://raw.githubusercontent.com/pac-labs/controller/main"


def read_remote(path: str) -> str | None:
    url = f"{GITHUB_RAW}/{path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PAC-local-diff/1"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"[diff] Warning: could not fetch {url} — {exc}", file=sys.stderr)
        return None


def get_local_version() -> str:
    v = (APPDIR / "VERSION").read_text(encoding="utf-8").strip()
    print(f"[diff] Local version: {v}")
    return v


def get_online_version() -> str | None:
    raw = read_remote("VERSION")
    if raw:
        v = raw.strip()
        print(f"[diff] Online version: {v}")
        return v
    return None


def bump_patch(v: str) -> str:
    parts = v.strip().lstrip("v").split(".")
    if len(parts) != 3:
        raise SystemExit(f"Unexpected VERSION format: {v!r}")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    return f"{major}.{minor}.{patch + 1}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate PAC local diff vs. GitHub main")
    parser.add_argument("--version", help="Version for output diff (e.g. 1.0.106). Default: online patch+1")
    parser.add_argument("--output-dir", default=".pac/diffs", help="Output directory (default: .pac/diffs)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing diff")
    args = parser.parse_args()

    local_ver = get_local_version()
    online_ver = get_online_version()

    if not args.version:
        args.version = bump_patch(online_ver or local_ver)

    out_dir = APPDIR / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    diff_path = out_dir / f"v{args.version}.diff"

    if diff_path.exists() and not args.force:
        print(f"[diff] {diff_path} already exists. Use --force to overwrite.")
        return 1

    has_git = (APPDIR / ".git").exists()
    if has_git:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", "origin/main"],
            cwd=APPDIR, text=True, capture_output=True,
        )
        has_git = result.returncode == 0

    if has_git:
        print("[diff] Using git diff origin/main...")
        result = subprocess.run(
            ["git", "diff", "--binary", "--no-color", "origin/main", "--", "."],
            cwd=APPDIR, capture_output=True, text=True,
        )
        diff_text = result.stdout
        if not diff_text.strip():
            print("[diff] No differences — nothing to release.")
            return 0
    else:
        print("[diff] No git repo; building file-by-file diff...")
        diff_lines: list[str] = []
        online_files = [
            "VERSION", "VERSION_CURRENT.md", "pyproject.toml", "requirements.txt",
            "README.md", "install.sh", "PAC_CHANGELOG.json",
        ]
        extra_dirs = ["pi_agent_platform", "scripts", "config", "deploy",
                      "containers", "docs", "vscode-extension", "binaries", "mcp"]

        def add_file_diff(local: Path) -> None:
            """Add a git-style diff for one file, comparing local vs online content."""
            rel = local.relative_to(APPDIR).as_posix()
            online = read_remote(rel)
            if online is None:
                return
            if not local.exists():
                return
            local_text = local.read_text(encoding="utf-8", errors="replace")
            if local_text == online:
                return
            # Git-style diff header
            diff_lines.append(f"diff --git a/{rel} b/{rel}")
            # Hunks
            ud = difflib.unified_diff(
                online.splitlines(),
                local_text.splitlines(),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                lineterm="",
            )
            for ln in ud:
                diff_lines.append(ln)

        for rel_path in online_files:
            add_file_diff(APPDIR / rel_path)

        for d in extra_dirs:
            online_index = read_remote(f"{d}/.gitkeep" if d != "pi_agent_platform" else f"{d}/__init__.py")
            if online_index is None:
                continue
            local_d = APPDIR / d
            if not local_d.exists():
                continue
            for fp in local_d.rglob("*"):
                if fp.is_file() and "__pycache__" not in fp.parts and not fp.name.endswith(".pyc"):
                    add_file_diff(fp)

        if not diff_lines:
            print("[diff] No differences found.")
            return 0
        diff_text = "\n".join(diff_lines) + "\n"

    diff_path.write_text(diff_text, encoding="utf-8")
    size = diff_path.stat().st_size
    print(f"[diff] Written: {diff_path} ({size:,} bytes)")
    print(f"[diff] Next steps:")
    print(f"  1. Copy {diff_path}")
    print(f"  2. Add to a PR branch at: .pac/diffs/v{args.version}.diff")
    print(f"  3. Label the PR: pac-apply-diff → workflow builds the release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())