#!/usr/bin/env python3
"""Validate a user-supplied PAC source diff before a privileged workflow applies it.

Accepted formats:
- git-style patches beginning with ``diff --git a/path b/path``
- unified ``diff -ruN`` patches generated from ``pac_orig/`` and ``pac_work/``

The validator is intentionally conservative because diff expansion workflows may
run with repository write permissions. It validates changed paths and rejects
binary/generated patches, workflow self-modification, secret-like files, and path
traversal. It does not execute code from the pull request branch.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

FORBIDDEN_PREFIXES = (
    ".git/",
    ".github/workflows/",
)
FORBIDDEN_NAMES = {".env", ".env.local"}
RELEASE_OWNED_FILES = {
    "VERSION",
    "VERSION_CURRENT.md",
    "MANIFEST.json",
    "PAC_CHANGELOG.json",
    "pyproject.toml",
}
GIT_PATH_RE = re.compile(r"^(?:diff --git a/(.*?) b/(.*?)|--- a/(.*)|\+\+\+ b/(.*))")
RUN_DIFF_RE = re.compile(r"^diff -[ruN]+(?:\s+'[^']+')*\s+(\S+)\s+(\S+)")
HEADER_PATH_RE = re.compile(r"^(?:---|\+\+\+)\s+(\S+)")


def fail(message: str) -> int:
    print(f"PAC diff validation failed: {message}", file=sys.stderr)
    return 1


def clean_path(raw: str | None) -> str | None:
    if not raw or raw == "/dev/null":
        return None
    path = raw.strip().strip('"')
    path = path.split("\t", 1)[0]
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    for prefix in ("pac_orig/", "pac_work/", "old/", "new/"):
        if path.startswith(prefix):
            path = path[len(prefix):]
    return path


def validate_path(path: str) -> str | None:
    if path.startswith("/") or "\x00" in path:
        return "absolute or null-containing paths are not allowed"
    parts = Path(path).parts
    if ".." in parts:
        return "path traversal is not allowed"
    if any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        return f"changes to {path} are not allowed through the diff expansion workflow"
    if Path(path).name in FORBIDDEN_NAMES:
        return f"changes to {path} look like secret/env files and are not allowed"
    return None


def iter_changed_paths(text: str):
    for line in text.splitlines():
        git_match = GIT_PATH_RE.match(line)
        if git_match:
            for raw in git_match.groups():
                path = clean_path(raw)
                if path:
                    yield path
            continue
        run_match = RUN_DIFF_RE.match(line)
        if run_match:
            for raw in run_match.groups():
                path = clean_path(raw)
                if path:
                    yield path
            continue
        header_match = HEADER_PATH_RE.match(line)
        if header_match:
            path = clean_path(header_match.group(1))
            if path:
                yield path


def main() -> int:
    if len(sys.argv) != 2:
        return fail("usage: validate-pac-diff.py <diff-file>")
    diff_path = Path(sys.argv[1])
    if not diff_path.is_file():
        return fail(f"diff file not found: {diff_path}")
    if diff_path.stat().st_size > 5 * 1024 * 1024:
        return fail("diff file is larger than 5 MiB")

    text = diff_path.read_text(encoding="utf-8", errors="replace")
    if "GIT binary patch" in text or "Binary files " in text:
        return fail("binary patches are not supported")
    if re.search(r"^(literal|delta) [0-9]+$", text, re.MULTILINE):
        return fail("binary patch sections are not supported")
    if not (text.startswith("diff --git ") or text.startswith("diff -ruN ") or text.startswith("diff -urN ") or text.startswith("diff -uN ")):
        return fail("diff must be git-style or unified diff -ruN format")

    seen: set[str] = set()
    meaningful: set[str] = set()
    for path in iter_changed_paths(text):
        seen.add(path)
        if path not in RELEASE_OWNED_FILES:
            meaningful.add(path)
        error = validate_path(path)
        if error:
            return fail(error)

    if not seen:
        return fail("no changed paths found in patch")
    if not meaningful:
        return fail("patch only changes release-owned metadata; no source changes remain")
    print(f"PAC diff validation passed for {len(seen)} path(s); {len(meaningful)} source path(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
