from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from typing import Any

from ..config import AppConfig, ToolConfig


@dataclass(slots=True)
class HookResult:
    ok: bool = True
    message: str = ""
    data: dict[str, Any] | None = None


def _tool_config(config: AppConfig, tool: str) -> ToolConfig | None:
    return config.tools.get(tool) if getattr(config, "tools", None) else None


def _run_hook_command(command: str, *, tool: str, phase: str, inp: dict[str, Any]) -> HookResult:
    if not command.strip():
        return HookResult()
    rendered = command.format(tool=shlex.quote(tool), phase=shlex.quote(phase))
    try:
        proc = subprocess.run(rendered, shell=True, text=True, capture_output=True, timeout=15)
    except Exception as exc:
        return HookResult(False, f"{phase} hook failed before execution: {exc}", {"error": str(exc)})
    data = {"returncode": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
    if proc.returncode != 0:
        return HookResult(False, f"{phase} hook failed for {tool}", data)
    return HookResult(True, proc.stdout.strip()[-500:], data)


def run_pre_hooks(config: AppConfig, tool: str, inp: dict[str, Any]) -> list[HookResult]:
    cfg = _tool_config(config, tool)
    commands = list(getattr(cfg, "pre_hooks", []) or []) if cfg else []
    return [_run_hook_command(command, tool=tool, phase="pre", inp=inp) for command in commands]


def run_post_hooks(config: AppConfig, tool: str, inp: dict[str, Any], observation: str, paused: bool) -> list[HookResult]:
    cfg = _tool_config(config, tool)
    commands = list(getattr(cfg, "post_hooks", []) or []) if cfg else []
    return [_run_hook_command(command, tool=tool, phase="post", inp=inp) for command in commands]
