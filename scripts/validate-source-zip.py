#!/usr/bin/env python3
"""Validate PAC source/update zips do not contain generated runtime artifacts."""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "dist/",
    "release-binaries/",
    "binaries/pac-agent/",
    "binaries/zed-binary/",
    "binaries/pac-endpoint-runner/",
)
FORBIDDEN_PARTS = (
    "/release-binaries/",
    "/__pycache__/",
)
FORBIDDEN_SUFFIXES = (
    ".pyc",
    ".pyo",
)
REQUIRED_ENTRIES = (
    "VERSION",
    "PAC_CHANGELOG.json",
    "pyproject.toml",
)
REQUIRED_PREFIXES = (
    "pi_agent_platform/",
    "binaries/pac-endpoint/",
    "binaries/pacctl/",
)


def validate_zip(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except Exception as exc:
        return [f"{path}: cannot open zip: {exc}"]

    names_set = set(names)
    for required in REQUIRED_ENTRIES:
        if required not in names_set:
            errors.append(f"{path.name}: missing required entry {required}")
    for prefix in REQUIRED_PREFIXES:
        if not any(name.startswith(prefix) for name in names):
            errors.append(f"{path.name}: missing required tree {prefix}")

    forbidden = [
        name for name in names
        if name.startswith(FORBIDDEN_PREFIXES)
        or any(part in f"/{name}" for part in FORBIDDEN_PARTS)
        or name.endswith(FORBIDDEN_SUFFIXES)
    ]
    if forbidden:
        sample = ", ".join(forbidden[:10])
        errors.append(f"{path.name}: contains generated/removed artifacts: {sample}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("zips", nargs="+", help="PAC source/update zip files to validate")
    args = parser.parse_args()

    errors: list[str] = []
    for raw in args.zips:
        errors.extend(validate_zip(Path(raw)))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("source zip validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
