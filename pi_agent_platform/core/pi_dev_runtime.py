from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def pi_container_source_version(root: Path) -> str | None:
    version_file = root / "containers" / "pi-agent-harness" / "VERSION"
    try:
        value = version_file.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return None
    return value or None


def inspect_pi_container_image(runtime: str | None, image: str) -> dict[str, Any]:
    info: dict[str, Any] = {
        "image": image,
        "runtime": runtime,
        "available": False,
        "labels": {},
        "version": None,
        "created": None,
    }
    if not runtime:
        info["reason"] = "No container runtime found."
        return info
    try:
        proc = subprocess.run(
            [runtime, "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        info["reason"] = str(exc)
        return info
    if proc.returncode != 0 or not proc.stdout.strip():
        info["reason"] = (proc.stderr or proc.stdout or "").strip() or "Image inspect failed."
        info["last_check"] = {
            "exit_code": proc.returncode,
            "stdout": (proc.stdout or "")[-1000:],
            "stderr": (proc.stderr or "")[-1000:],
        }
        return info
    try:
        payload = json.loads(proc.stdout)
        record = payload[0] if isinstance(payload, list) and payload else payload
    except Exception as exc:
        info["reason"] = f"Could not parse image inspect output: {exc}"
        return info
    labels = {}
    if isinstance(record, dict):
        config = record.get("Config") or {}
        labels = config.get("Labels") or {}
        info["created"] = record.get("Created")
    info["available"] = True
    info["labels"] = labels if isinstance(labels, dict) else {}
    info["version"] = (
        info["labels"].get("pac.pi_container.version")
        or info["labels"].get("org.opencontainers.image.version")
    )
    return info


def pi_container_rebuild_state(image_info: dict[str, Any], expected_version: str | None) -> dict[str, Any]:
    actual = str(image_info.get("version") or "").strip() or None
    if not image_info.get("available"):
        return {
            "needs_rebuild": True,
            "reason": image_info.get("reason") or "pi.dev image is missing.",
            "expected_version": expected_version,
            "actual_version": actual,
        }
    if expected_version and actual != expected_version:
        return {
            "needs_rebuild": True,
            "reason": f"pi.dev image version {actual or 'unknown'} does not match source version {expected_version}.",
            "expected_version": expected_version,
            "actual_version": actual,
        }
    return {
        "needs_rebuild": False,
        "reason": "pi.dev image matches the current source version.",
        "expected_version": expected_version,
        "actual_version": actual,
    }
