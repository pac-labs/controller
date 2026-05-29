#!/usr/bin/env python3
"""Validate that PAC release packaging is gated by binary compilation."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_CANDIDATES = [ROOT / ".github/workflows/pac-release.yml", ROOT / "github/workflows/pac-release.yml"]


def fail(message: str) -> None:
    raise SystemExit(f"release binary pipeline validation failed: {message}")


def validate_workflow(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "push:" not in text or "branches: [main]" not in text:
        fail(f"{path} does not run on push to main")
    compile_idx = text.find("scripts/compile-release-binaries.py")
    package_idx = text.find("scripts/generate-pac-release.py")
    if compile_idx == -1:
        fail(f"{path} does not compile release binaries")
    if package_idx == -1:
        fail(f"{path} does not generate PAC release artifacts")
    if compile_idx > package_idx:
        fail(f"{path} packages before compiling binaries")
    if "dist/pac-endpoint-*" not in text or "dist/pacctl-*" not in text:
        fail(f"{path} does not upload direct pac-endpoint and pacctl assets")


def validate_scripts() -> None:
    compile_text = (ROOT / "scripts/compile-release-binaries.py").read_text(encoding="utf-8")
    if "PRIMARY_RELEASE_BINARIES = (\"pac-endpoint\", \"pacctl\")" not in compile_text:
        fail("compile-release-binaries.py must limit primary release binaries to pac-endpoint and pacctl")
    for target in ("darwin/amd64", "darwin/arm64"):
        if target not in compile_text:
            fail(f"compile-release-binaries.py must build macOS/OSX target {target}")
    release_text = (ROOT / "scripts/generate-pac-release.py").read_text(encoding="utf-8")
    if "Run scripts/compile-release-binaries.py before scripts/generate-pac-release.py" not in release_text:
        fail("generate-pac-release.py must fail clearly when binaries were not compiled first")
    if "must not contain bundled release binaries" not in release_text:
        fail("generate-pac-release.py must validate source/update zips do not bundle binaries")


def main() -> int:
    found = [path for path in WORKFLOW_CANDIDATES if path.exists()]
    if not found:
        fail("no pac-release workflow found")
    for path in found:
        validate_workflow(path)
    validate_scripts()
    print("release binary pipeline validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
