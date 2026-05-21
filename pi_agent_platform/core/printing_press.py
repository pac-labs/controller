from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import Any


PRINTING_PRESS_BINARIES = (
    "printing-press",
    "printing_press",
    "printingpress",
    "press",
)


def _candidate_binary() -> str:
    for name in PRINTING_PRESS_BINARIES:
        if shutil_which(name):
            return name
    return PRINTING_PRESS_BINARIES[0]


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def build_printing_press_command(inp: dict[str, Any], workspace_path: str) -> list[str]:
    data = inp or {}
    explicit = str(data.get("command") or "").strip()
    args = data.get("args")
    path = str(data.get("path") or "").strip()
    mode = str(data.get("mode") or "optimize").strip() or "optimize"
    binary = _candidate_binary()
    if explicit:
        return [binary, *shlex.split(explicit)]
    if isinstance(args, list) and args:
        return [binary, *[str(item) for item in args if str(item).strip()]]
    if path:
        return [binary, mode, path]
    return [binary, mode, workspace_path]


async def run_printing_press(inp: dict[str, Any], workspace_path: str) -> tuple[str, bool]:
    command = build_printing_press_command(inp, workspace_path)
    binary = command[0]
    if not shutil_which(binary):
        hint = (
            "PRINTING_PRESS_UNAVAILABLE: install the Printing Press CLI or expose it on PATH. "
            "Expected one of: printing-press, printing_press, printingpress, press."
        )
        return hint, False
    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=workspace_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    out = stdout.decode(errors="replace").strip()
    err = stderr.decode(errors="replace").strip()
    text = out or err or f"{binary} exited {proc.returncode}"
    if err and out:
        text = f"{out}\n\nstderr:\n{err}"
    return text[-12000:], False
