#!/usr/bin/env python3
"""Compile all PAC Go binary components for release packaging.

The controller/PAC release version is intentionally not used as the binary
component version. Each binary component owns its own VERSION or
pac-component.json version, so unchanged binary sources do not get renamed just
because PAC itself released a new controller build.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = (
    "linux/amd64",
    "linux/arm64",
    "darwin/amd64",
    "darwin/arm64",
    "windows/amd64",
)


class BuildError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def component_version(folder: Path) -> str:
    version_file = folder / "VERSION"
    if version_file.exists():
        first = version_file.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        if first and first[0].strip():
            return first[0].strip()
    meta = read_json(folder / "pac-component.json")
    value = str(meta.get("version") or "").strip()
    return value or "dev"


def component_id(folder: Path) -> str:
    meta = read_json(folder / "pac-component.json")
    return str(meta.get("id") or folder.name).strip() or folder.name


def binary_name(folder: Path) -> str:
    meta = read_json(folder / "pac-component.json")
    value = str(meta.get("binary_name") or meta.get("id") or folder.name).strip()
    return value or folder.name


PRIMARY_RELEASE_BINARIES = ("pac-endpoint", "pacctl")
TRANSITIONAL_SOURCE_ONLY_BINARIES: tuple[str, ...] = ()
REMOVED_BINARIES = ("pac-endpoint-runner", "pac-agent", "zed-binary")


def discover_binary_projects(root: Path) -> list[Path]:
    """Return only first-class release binaries.

    Only first-class binaries are release assets. Removed binary directories are intentionally ignored even if a stale checkout still has them.
    """
    base = root / "binaries"
    if not base.exists():
        return []
    projects = []
    for name in PRIMARY_RELEASE_BINARIES:
        folder = base / name
        if folder.is_dir() and (folder / "go.mod").is_file() and (folder / "main.go").is_file():
            projects.append(folder)
    return projects


def ldflags_for(folder: Path, version: str) -> str:
    base = [
        "-s",
        "-w",
        f"-X main.version={version}",
        "-X main.defaultServerURL=",
        "-X main.defaultControllerID=",
        "-X main.defaultUpdateChannel=stable",
    ]
    # pac-endpoint exposes endpoint-specific defaults in addition to the shared
    # controller connection defaults. Supplying these flags to binaries that do
    # not define the symbols is harmless for Go builds, but keeping the list
    # scoped makes the build contract explicit.
    if folder.name == "pac-endpoint":
        base.extend([
            "-X main.defaultEndpointName=",
            "-X main.defaultRunnerEnabled=true",
            "-X main.defaultWorkspaceRoot=",
        ])
    return " ".join(base)


def compile_project(folder: Path, out_root: Path, targets: list[str], *, dry_run: bool = False) -> list[dict[str, Any]]:
    version = component_version(folder)
    name = binary_name(folder)
    records: list[dict[str, Any]] = []
    for target in targets:
        if "/" not in target:
            raise BuildError(f"Invalid target {target!r}; expected GOOS/GOARCH")
        goos, goarch = target.split("/", 1)
        target_dir = out_root / folder.name / f"{goos}-{goarch}"
        ext = ".exe" if goos == "windows" else ""
        asset_name = f"{name}-{goos}-{goarch}{ext}"
        output = target_dir / asset_name
        record = {
            "project": folder.name,
            "component_id": component_id(folder),
            "component_version": version,
            "version": version,
            "role": "endpoint-wrapper" if folder.name == "pac-endpoint" else "pac-client",
            "required": True,
            "lifecycle": "primary",
            "target": target,
            "goos": goos,
            "goarch": goarch,
            "asset_name": asset_name,
            "download_name": asset_name,
            "path": output.relative_to(out_root.parent).as_posix(),
        }
        if dry_run:
            record.update({"filename": output.name, "size": 0, "sha256": ""})
            records.append(record)
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update({"GOOS": goos, "GOARCH": goarch, "CGO_ENABLED": "0"})
        proc = subprocess.run(
            ["go", "build", "-trimpath", "-ldflags", ldflags_for(folder, version), "-o", str(output), "."],
            cwd=folder,
            env=env,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise BuildError(f"binary build failed for {folder.name} {target}\n{proc.stdout}\n{proc.stderr}")
        data = output.read_bytes()
        record.update({
            "filename": output.name,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
        records.append(record)
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="dist/release-binaries", help="Output directory for compiled binaries")
    parser.add_argument("--targets", default=",".join(DEFAULT_TARGETS), help="Comma-separated GOOS/GOARCH targets")
    parser.add_argument("--dry-run", action="store_true", help="Write only the manifest without invoking go build")
    args = parser.parse_args()

    out_root = (ROOT / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    targets = [item.strip() for item in args.targets.split(",") if item.strip()]
    if not targets:
        raise SystemExit("No binary targets requested")
    if out_root.exists() and not args.dry_run:
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    built: list[dict[str, Any]] = []
    for project in discover_binary_projects(ROOT):
        built.extend(compile_project(project, out_root, targets, dry_run=args.dry_run))

    manifest = {
        "schema": "pac.release-binaries.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_count": len(targets),
        "project_count": len(discover_binary_projects(ROOT)),
        "binary_count": len(built),
        "binaries": built,
        "version_policy": "component-owned",
        "delivery": "direct-github-release-assets",
        "source_zip_bundles_binaries": False,
        "primary_binaries": list(PRIMARY_RELEASE_BINARIES),
        "transitional_source_only_binaries": list(TRANSITIONAL_SOURCE_ONLY_BINARIES),
        "removed_binaries": list(REMOVED_BINARIES),
    }
    manifest_path = out_root / "RELEASE_BINARIES.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuildError as exc:
        raise SystemExit(str(exc)) from exc
