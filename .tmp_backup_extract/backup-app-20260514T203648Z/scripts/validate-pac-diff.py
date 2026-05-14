#!/usr/bin/env python3
"""Validate a user-supplied PAC git diff before a privileged workflow applies it.

The workflow intentionally reads only a diff file from a PR branch, checks it out
into a separate directory, and applies the patch to main. This script keeps the
patch format predictable and blocks path traversal / binary patch payloads.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

FORBIDDEN_PREFIXES = (
    ".git/",
    ".github/workflows/apply-diff-pr.yml",
)
FORBIDDEN_NAMES = {".env", ".env.local"}
PATH_RE = re.compile(r"^(?:diff --git a/(.*?) b/(.*?)|--- a/(.*)|\+\+\+ b/(.*))$")


def fail(message: str) -> int:
    print(f"PAC diff validation failed: {message}", file=sys.stderr)
    return 1


def clean_path(raw: str | None) -> str | None:
    if not raw or raw == "/dev/null":
        return None
    path = raw.strip().strip('"')
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path


def validate_path(path: str) -> str | None:
    if path.startswith("/") or "\x00" in path:
        return "absolute or null-containing paths are not allowed"
    parts = Path(path).parts
    if ".." in parts:
        return "path traversal is not allowed"
    if any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        return f"changes to {path} are not allowed through the diff auto-apply workflow"
    if Path(path).name in FORBIDDEN_NAMES:
        return f"changes to {path} look like secret/env files and are not allowed"
    return None


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
    if not text.startswith("diff --git "):
        return fail("diff must be a git-style patch starting with 'diff --git'")

    seen: set[str] = set()
    for line in text.splitlines():
        match = PATH_RE.match(line)
        if not match:
            continue
        for raw in match.groups():
            path = clean_path(raw)
            if not path:
                continue
            seen.add(path)
            error = validate_path(path)
            if error:
                return fail(error)

    if not seen:
        return fail("no changed paths found in patch")
    print(f"PAC diff validation passed for {len(seen)} path(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
