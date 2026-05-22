#!/usr/bin/env python3
"""Generate PAC release artifacts for GitHub Releases.

Outputs:
  dist/pac-full.zip
  dist/pac-patch.zip
  dist/PAC_RELEASE_MANIFEST.json
  dist/PAC_UPDATE_DIFF.diff when a previous git ref exists

GitHub is the version authority. The workflow writes the generated version into
VERSION/PAC_CHANGELOG inside the checked-out workspace before this script runs,
but artifact filenames stay stable to avoid local/manual version skew.

The patch artifact is intentionally a complete, webUI-safe PAC app package.
PAC's updater replaces project-owned directories from the uploaded root; a
partial pi_agent_platform/ directory would be unsafe. The manifest records the
real changed files so the UI/release notes can still show a delta.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
EXCLUDES = {
    ".git",
    ".github/.cache",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    "dist",
    "build",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".swp"}
INCLUDE_ROOTS = [
    ".github",
    "binaries",
    "config",
    "containers",
    "deploy",
    "docs",
    "mcp",
    "pi_agent_platform",
    "scripts",
    "vscode-extension",
]
INCLUDE_FILES = [
    "FEATURE_PACK.md",
    "FILES.txt",
    "MANIFEST.json",
    "PAC_CHANGELOG.json",
    "README.md",
    "VERSION",
    "VERSION_CURRENT.md",
    "docs-zed-mcp-example.json",
    "install.sh",
    "pyproject.toml",
    "requirements.txt",
]


def run(cmd: list[str], *, check: bool = True) -> str:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def git_available() -> bool:
    return (ROOT / ".git").exists() and subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT, capture_output=True).returncode == 0


def latest_previous_tag(current: str) -> str | None:
    if not git_available():
        return None
    tags = run(["git", "tag", "--list", "v*"], check=False).splitlines()
    tags = [tag for tag in tags if tag != f"v{current}" and re.match(r"^v\d+\.\d+\.\d+$", tag)]
    if not tags:
        return None
    tags.sort(key=lambda t: tuple(int(p) for p in t[1:].split(".")))
    return tags[-1]


def changed_files(previous_ref: str | None) -> list[str]:
    if not git_available() or not previous_ref:
        return []
    out = run(["git", "diff", "--name-only", f"{previous_ref}..HEAD"], check=False)
    return sorted(line.strip() for line in out.splitlines() if line.strip())


def write_update_diff(ver: str, previous_ref: str | None) -> Path:
    """Write the update diff asset. It is git-style when Git history is available."""
    out = DIST / "PAC_UPDATE_DIFF.diff"
    if git_available() and previous_ref:
        diff = run(["git", "diff", "--binary", f"{previous_ref}..HEAD"], check=False)
        if diff.strip():
            out.write_text(diff, encoding="utf-8")
            return out
    out.write_text("# No git diff was available for this release build.\n", encoding="utf-8")
    return out


def should_skip(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    parts = rel.split("/")
    if any(part in EXCLUDES for part in parts):
        return True
    if any(rel == ex or rel.startswith(ex + "/") for ex in EXCLUDES):
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    if path.name.endswith("~"):
        return True
    if path.is_file() and path.stat().st_size > 50 * 1024 * 1024:
        return True
    return False


def iter_package_files() -> Iterable[Path]:
    seen: set[Path] = set()
    for name in INCLUDE_FILES:
        p = ROOT / name
        if p.exists() and not should_skip(p):
            seen.add(p)
            yield p
    for root_name in INCLUDE_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file() and not should_skip(p) and p not in seen:
                seen.add(p)
                yield p
def _empty_changelog() -> dict:
    return {"releases": [], "current_version": version()}


def _try_parse_changelog(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Older/generated diffs have occasionally left a dangling comma before
        # the final object/array close. Repair that safe JSON-shape issue so the
        # release workflow can continue and then rewrite canonical JSON below.
        repaired = re.sub(r",(\s*[}\]])", r"\1", text)
        data = json.loads(repaired)
    if not isinstance(data, dict):
        return _empty_changelog()
    return data


def load_changelog() -> dict:
    path = ROOT / "PAC_CHANGELOG.json"
    if not path.exists():
        return _empty_changelog()
    try:
        data = _try_parse_changelog(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            "PAC_CHANGELOG.json is not valid JSON and could not be repaired. "
            f"Check line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    # PAC historically used both `releases` and `entries`. Normalize to the
    # user-facing `releases` list and preserve any old entries by appending them.
    releases = data.get("releases")
    if not isinstance(releases, list):
        releases = []
    legacy_entries = data.get("entries")
    if isinstance(legacy_entries, list):
        known = {str(item.get("version")) for item in releases if isinstance(item, dict)}
        for item in legacy_entries:
            if isinstance(item, dict) and str(item.get("version")) not in known:
                releases.append(item)
                known.add(str(item.get("version")))
    return {"releases": releases, "current_version": str(data.get("current_version") or version())}


def release_entry(ver: str) -> dict:
    changed_path = ROOT / f"changed_{ver}.txt"
    changes: list[str] = []
    if changed_path.exists():
        for raw in changed_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("- "):
                changes.append(line[2:].strip())
    if not changes:
        changes = ["PAC release artifact generated by GitHub Actions."]
    return {
        "version": ver,
        "date": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "summary": f"PAC v{ver} release generated by GitHub Actions.",
        "changes": changes,
    }


def ensure_changelog(ver: str) -> dict:
    data = load_changelog()
    releases = data.setdefault("releases", [])
    if not any(str(entry.get("version")) == ver for entry in releases if isinstance(entry, dict)):
        releases.insert(0, release_entry(ver))
    data["current_version"] = ver
    (ROOT / "PAC_CHANGELOG.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def write_zip(out: Path) -> None:
    files = sorted(iter_package_files(), key=lambda p: p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in files:
            zf.write(p, p.relative_to(ROOT).as_posix())
    # Validate it can be opened and has the PAC app root markers.
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        required = {"pyproject.toml", "VERSION", "PAC_CHANGELOG.json"}
        missing = sorted(required - names)
        if missing:
            raise SystemExit(f"{out.name} missing required entries: {missing}")
        if not any(name.startswith("pi_agent_platform/") for name in names):
            raise SystemExit(f"{out.name} missing pi_agent_platform/")


def write_packages_seed_zip(ver: str) -> Path:
    seed_dir = DIST / "packages-seed"
    if seed_dir.exists():
        shutil.rmtree(seed_dir)
    seed_dir.mkdir(parents=True, exist_ok=True)
    run([sys.executable, "scripts/generate-package-repo.py", "--source", str(ROOT), "--out", str(seed_dir), "--version", ver])
    out = DIST / "pac-packages-seed.zip"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(seed_dir.rglob("*")):
            if p.is_file() and p.suffix not in EXCLUDE_SUFFIXES and not any(part in EXCLUDES for part in p.relative_to(seed_dir).parts):
                zf.write(p, p.relative_to(seed_dir).as_posix())
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        if "packages.json" not in names or "VERSION" not in names:
            raise SystemExit(f"{out.name} missing package repository markers")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default=version())
    parser.add_argument("--previous-ref", default=os.environ.get("PAC_PREVIOUS_REF"))
    args = parser.parse_args()

    ver = args.version
    if ver != version():
        raise SystemExit(f"--version {ver} does not match VERSION {version()}")

    previous_ref = args.previous_ref or latest_previous_tag(ver)
    changed = changed_files(previous_ref)
    changelog = ensure_changelog(ver)

    DIST.mkdir(exist_ok=True)
    full = DIST / "pac-full.zip"
    patch = DIST / "pac-patch.zip"
    write_zip(full)
    write_zip(patch)
    packages_seed = write_packages_seed_zip(ver)
    update_diff = write_update_diff(ver, previous_ref)

    manifest = {
        "schema": "pac.release.v1",
        "version": ver,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "previous_ref": previous_ref,
        "artifacts": {
            "full": full.name,
            "patch": patch.name,
            "changelog": "PAC_CHANGELOG.json",
            "packages_seed": packages_seed.name,
            "update_diff": update_diff.name,
        },
        "changed_files": changed,
        "changelog_entry": next((e for e in changelog.get("entries", []) if isinstance(e, dict) and str(e.get("version")) == ver), None),
    }
    manifest_path = DIST / "PAC_RELEASE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
