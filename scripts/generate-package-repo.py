#!/usr/bin/env python3
"""Generate the pac-labs/packages repository from controller source packages."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

PACKAGE_ROOTS = ("binaries", "containers", "plugins", "scripts", "docs")
IGNORE_NAMES = {".git", "__pycache__", "node_modules", "dist", ".pytest_cache"}


def ignore(dir_path: str, names: list[str]) -> set[str]:
    return {name for name in names if name.startswith(".") or name in IGNORE_NAMES or name.endswith(".pyc")}


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def collect_components(out: Path) -> list[dict]:
    components: list[dict] = []
    for meta_path in sorted(out.glob("**/pac-component.json")):
        if any(part in IGNORE_NAMES for part in meta_path.parts):
            continue
        rel = meta_path.parent.relative_to(out).as_posix()
        data = read_json(meta_path)
        data.setdefault("id", rel.replace("/", ":"))
        data.setdefault("title", meta_path.parent.name.replace("-", " ").title())
        data.setdefault("source_path", rel)
        components.append(data)
    return sorted(components, key=lambda c: str(c.get("source_path", c.get("id", ""))))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=".", help="Controller repository root")
    parser.add_argument("--out", required=True, help="Output directory for pac-labs/packages contents")
    parser.add_argument("--version", default=None, help="PAC package version")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    out = Path(args.out).resolve()
    version = args.version or (source / "VERSION").read_text(encoding="utf-8").strip()

    out.mkdir(parents=True, exist_ok=True)
    for root in PACKAGE_ROOTS:
        target = out / root
        if target.exists():
            shutil.rmtree(target)
        src = source / root
        if src.exists():
            shutil.copytree(src, target, ignore=ignore)
        else:
            target.mkdir(parents=True, exist_ok=True)

    components = collect_components(out)
    manifest = {
        "schema": "pac-packages.v1",
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": "https://github.com/pac-labs/packages",
        "controller_repository": "https://github.com/pac-labs/controller",
        "package_roots": list(PACKAGE_ROOTS),
        "component_count": len(components),
        "components": components,
    }
    (out / "packages.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out / "VERSION").write_text(version + "\n", encoding="utf-8")
    (out / "README.md").write_text(
        "# PAC packages\n\n"
        "This repository is generated from `pac-labs/controller`. It mirrors the source-package directories used by the PAC Source Library.\n\n"
        "Package roots:\n\n"
        + "".join(f"- `{root}/`\n" for root in PACKAGE_ROOTS)
        + "\nEach component can include `pac-component.json` for title, description, maintainers, version, and package metadata.\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
