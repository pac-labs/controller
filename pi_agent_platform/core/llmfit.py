from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


LLMFIT_IMAGE = "ghcr.io/alexsjones/llmfit:0.9.30"


def llmfit_binary() -> str | None:
    return shutil.which("llmfit")


def llmfit_container_runtime() -> str | None:
    for candidate in ("podman", "docker"):
        if shutil.which(candidate):
            return candidate
    return None


def llmfit_status(*, timeout_seconds: float = 10.0) -> dict[str, Any]:
    source = _preferred_source()
    if source["kind"] == "container":
        version = _run_plain(_container_command(["--version"]), timeout_seconds=timeout_seconds)
        system = _run_json(_container_command(["--json", "system"]), timeout_seconds=timeout_seconds)
        return {
            "ok": bool(system.get("ok")),
            "installed": True,
            "source": "container",
            "runtime": source.get("runtime"),
            "image": LLMFIT_IMAGE,
            "binary": None,
            "version": version.get("output"),
            "system": system.get("payload") if system.get("ok") else None,
            "error": None if system.get("ok") else system.get("error"),
        }
    binary = source.get("binary")
    if not binary:
        return {"ok": False, "installed": False, "reason": "llmfit_not_installed", "source": "missing"}
    version = _run_plain([binary, "--version"], timeout_seconds=timeout_seconds)
    system = _run_json([binary, "--json", "system"], timeout_seconds=timeout_seconds)
    return {
        "ok": bool(system.get("ok")),
        "installed": True,
        "source": "binary",
        "runtime": None,
        "image": None,
        "binary": binary,
        "version": version.get("output"),
        "system": system.get("payload") if system.get("ok") else None,
        "error": None if system.get("ok") else system.get("error"),
    }


def llmfit_recommendations(
    *,
    use_case: str = "coding",
    limit: int = 5,
    max_context: int | None = None,
    force_runtime: str | None = None,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    source = _preferred_source()
    if source["kind"] == "container":
        command = _container_command([
            "recommend",
            "--json",
            "--use-case",
            use_case,
            "--limit",
            str(max(1, min(limit, 10))),
        ])
        if max_context:
            command.extend(["--max-context", str(max_context)])
        if force_runtime:
            command.extend(["--force-runtime", force_runtime])
        result = _run_json(command, timeout_seconds=timeout_seconds)
        return {
            "ok": bool(result.get("ok")),
            "installed": True,
            "source": "container",
            "runtime": source.get("runtime"),
            "image": LLMFIT_IMAGE,
            "binary": None,
            "command": command,
            "use_case": use_case,
            "limit": limit,
            "max_context": max_context,
            "force_runtime": force_runtime,
            "recommendations": _normalize_recommendations(result.get("payload")),
            "raw": result.get("payload") if result.get("ok") else None,
            "error": None if result.get("ok") else result.get("error"),
        }
    binary = source.get("binary")
    if not binary:
        return {"ok": False, "installed": False, "reason": "llmfit_not_installed", "source": "missing"}
    command = [binary, "recommend", "--json", "--use-case", use_case, "--limit", str(max(1, min(limit, 10)))]
    if max_context:
        command = [binary, "--max-context", str(max_context), *command[1:]]
    if force_runtime:
        command.extend(["--force-runtime", force_runtime])
    result = _run_json(command, timeout_seconds=timeout_seconds)
    return {
        "ok": bool(result.get("ok")),
        "installed": True,
        "source": "binary",
        "runtime": None,
        "image": None,
        "binary": binary,
        "command": command,
        "use_case": use_case,
        "limit": limit,
        "max_context": max_context,
        "force_runtime": force_runtime,
        "recommendations": _normalize_recommendations(result.get("payload")),
        "raw": result.get("payload") if result.get("ok") else None,
        "error": None if result.get("ok") else result.get("error"),
    }


def _preferred_source() -> dict[str, Any]:
    runtime = llmfit_container_runtime()
    if runtime:
        return {"kind": "container", "runtime": runtime}
    binary = llmfit_binary()
    if binary:
        return {"kind": "binary", "binary": binary}
    return {"kind": "missing"}


def _container_command(args: list[str]) -> list[str]:
    runtime = llmfit_container_runtime()
    if not runtime:
        raise RuntimeError("No container runtime found for llmfit")
    command = [runtime, "run", "--rm", "--pull=missing", LLMFIT_IMAGE]
    if runtime == "podman":
        command.insert(2, "--quiet")
    command.extend(args)
    return command


def _run_json(command: list[str], *, timeout_seconds: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(3.0, timeout_seconds),
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    output = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode != 0:
        return {"ok": False, "error": output[-4000:] or f"llmfit exited with {completed.returncode}"}
    try:
        return {"ok": True, "payload": json.loads(output)}
    except Exception:
        return {"ok": False, "error": f"Invalid llmfit JSON output: {output[-4000:]}"}


def _run_plain(command: list[str], *, timeout_seconds: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(3.0, timeout_seconds),
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    output = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode != 0:
        return {"ok": False, "error": output[-4000:] or f"llmfit exited with {completed.returncode}"}
    return {"ok": True, "output": output}


def _normalize_recommendations(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("recommendations") or payload.get("results") or payload.get("models") or []
    else:
        items = []
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "name": item.get("name") or item.get("model") or item.get("id"),
                "runtime": item.get("runtime") or item.get("provider"),
                "quantization": item.get("quantization") or item.get("quant"),
                "context_length": item.get("context_length") or item.get("context") or item.get("ctx"),
                "score": item.get("score"),
                "fit": item.get("fit") or item.get("fit_score"),
                "speed": item.get("speed") or item.get("speed_score"),
                "quality": item.get("quality") or item.get("quality_score"),
                "raw": item,
            }
        )
    return normalized
