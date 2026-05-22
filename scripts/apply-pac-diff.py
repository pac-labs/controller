#!/usr/bin/env python3
"""Apply a PAC source diff to the current checkout.

This helper is used by the diff-expansion workflow. It can apply either git-style
patches or ``diff -ruN pac_orig pac_work`` patches and strips release-owned
metadata files by default because GitHub release workflows own version markers,
release manifests, and changelog finalization.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

RELEASE_OWNED_FILES = {
    "VERSION",
    "VERSION_CURRENT.md",
    "MANIFEST.json",
    "PAC_CHANGELOG.json",
    "pyproject.toml",
}


def normalize_path(raw: str) -> str:
    path = raw.strip().split("\t", 1)[0].strip('"')
    if path in {"/dev/null", ""}:
        return path
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    for prefix in ("pac_orig/", "pac_work/", "old/", "new/"):
        if path.startswith(prefix):
            path = path[len(prefix):]
    return path


def block_file_from_header(line: str) -> str | None:
    if line.startswith("diff --git "):
        parts = line.strip().split()
        if len(parts) >= 4:
            return normalize_path(parts[3])
        if len(parts) >= 3:
            return normalize_path(parts[2])
    if line.startswith(("diff -ruN ", "diff -urN ", "diff -uN ")):
        parts = line.strip().split()
        if len(parts) >= 4:
            return normalize_path(parts[-1])
    return None


def strip_metadata_blocks(text: str) -> str:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    current: list[str] = []
    current_file: str | None = None

    def flush() -> None:
        nonlocal current, current_file
        if current and current_file not in RELEASE_OWNED_FILES:
            out.extend(current)
        current = []
        current_file = None

    for line in lines:
        if line.startswith("diff --git ") or line.startswith(("diff -ruN ", "diff -urN ", "diff -uN ")):
            flush()
            current = [line]
            current_file = block_file_from_header(line)
            continue
        if current:
            if current_file is None and line.startswith("+++ "):
                current_file = normalize_path(line[4:])
            current.append(line)
        else:
            out.append(line)
    flush()
    return "".join(out)


def run(cmd: list[str], *, cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("diff_file")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--keep-release-metadata", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    diff_path = Path(args.diff_file).resolve()
    text = diff_path.read_text(encoding="utf-8", errors="replace")
    if not args.keep_release_metadata:
        text = strip_metadata_blocks(text)
    if "diff --git " not in text and "diff -ruN " not in text and "diff -urN " not in text and "diff -uN " not in text:
        raise SystemExit("PAC diff has no source changes after stripping release metadata")

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".diff", delete=False) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    try:
        if text.startswith("diff --git "):
            run(["git", "apply", "--whitespace=fix", str(tmp_path)], cwd=repo)
        else:
            # diff -ruN pac_orig/foo pac_work/foo applies cleanly with -p1.
            run(["patch", "-p1", "--forward", "--batch", "--input", str(tmp_path)], cwd=repo)
    finally:
        tmp_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
