from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .scanner import safe_root


_CS_TYPE_RE = re.compile(r"^\s*(?:public|private|internal|protected|abstract|sealed|partial|static|\s)*(?:class|interface|record|struct)\s+(?P<name>[A-Za-z_]\w*)\s*(?::\s*(?P<bases>[^ {]+(?:\s*,\s*[^ {]+)*))?")
_CS_METHOD_RE = re.compile(r"^\s*(?:public|private|internal|protected|static|async|virtual|override|sealed|partial|\s)+(?:[A-Za-z_][\w<>?\[\],.]*\s+)+(?P<name>[A-Za-z_]\w*)\s*\([^;]*\)\s*(?:\{|=>)")
_TFM_RE = re.compile(r"<TargetFrameworks?>(?P<tfm>[^<]+)</TargetFrameworks?>")


def analyze_csharp(root: Path, *, path: str = ".", run: bool = False, timeout: int = 120) -> dict[str, Any]:
    base = safe_root(root, path)
    if base.is_file():
        base = base.parent
    solutions = sorted(base.rglob("*.sln"))[:40]
    projects = sorted(base.rglob("*.csproj"))[:120]
    files = sorted(base.rglob("*.cs"))[:5000]
    project_rows = [_project_row(base, project) for project in projects]
    symbols = _collect_symbols(base, files)
    relationships = _relationships(symbols)
    dotnet = shutil.which("dotnet")
    build_result: dict[str, Any] | None = None
    if run:
        build_result = _run_dotnet(base, timeout=timeout) if dotnet else {"error": "dotnet not found"}
    summary = f"Found {len(project_rows)} C# projects, {len(solutions)} solutions, {len(symbols)} symbols."
    return {
        "mode": "csharp-static-roslyn-readiness",
        "summary": summary,
        "dotnet_available": bool(dotnet),
        "dotnet_path": dotnet,
        "solution_count": len(solutions),
        "project_count": len(project_rows),
        "solutions": [str(item.relative_to(base)) for item in solutions],
        "projects": project_rows,
        "symbol_count": len(symbols),
        "symbols": symbols[:300],
        "relationships": relationships[:300],
        "build": build_result,
        "diagnostics_preview": _diagnostics_preview(build_result),
        "next_steps": _next_steps(bool(dotnet), bool(project_rows)),
    }


def _project_row(base: Path, project: Path) -> dict[str, Any]:
    text = project.read_text(errors="replace")
    tfm = _TFM_RE.search(text)
    refs = re.findall(r"<ProjectReference\s+Include=\"([^\"]+)\"", text)
    packages = re.findall(r"<PackageReference\s+Include=\"([^\"]+)\"(?:\s+Version=\"([^\"]+)\")?", text)
    return {
        "name": project.stem,
        "path": str(project.relative_to(base)),
        "target_framework": tfm.group("tfm") if tfm else None,
        "project_references": refs[:50],
        "package_references": [{"name": name, "version": version or None} for name, version in packages[:80]],
    }


def _collect_symbols(base: Path, files: list[Path]) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    current_type: str | None = None
    for file in files:
        try:
            lines = file.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for index, line in enumerate(lines, start=1):
            type_match = _CS_TYPE_RE.search(line)
            if type_match:
                current_type = type_match.group("name")
                symbols.append({
                    "kind": "type",
                    "name": current_type,
                    "file": str(file.relative_to(base)),
                    "line": index,
                    "bases": [part.strip() for part in (type_match.group("bases") or "").split(",") if part.strip()],
                })
                continue
            method_match = _CS_METHOD_RE.search(line)
            if method_match:
                symbols.append({
                    "kind": "method",
                    "name": method_match.group("name"),
                    "container": current_type,
                    "file": str(file.relative_to(base)),
                    "line": index,
                    "signature": line.strip(),
                })
    return symbols


def _relationships(symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for symbol in symbols:
        if symbol.get("kind") != "type":
            continue
        for base in symbol.get("bases") or []:
            rows.append({"from": symbol.get("name"), "to": base, "kind": "inherits_or_implements", "file": symbol.get("file"), "line": symbol.get("line")})
    return rows


def _run_dotnet(base: Path, *, timeout: int) -> dict[str, Any]:
    command = ["dotnet", "build", "--no-restore", "--nologo"]
    try:
        proc = subprocess.run(command, cwd=str(base), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=max(10, min(timeout, 600)))
    except subprocess.TimeoutExpired:
        return {"command": command, "error": f"timed out after {timeout}s"}
    return {"command": command, "exit_code": proc.returncode, "stdout": proc.stdout[-12000:], "stderr": proc.stderr[-12000:]}


def _diagnostics_preview(result: dict[str, Any] | None) -> str:
    if not result:
        return ""
    text = "\n".join(part for part in [result.get("stdout"), result.get("stderr"), result.get("error")] if part)
    lines = [line for line in text.splitlines() if ": error " in line.lower() or ": warning " in line.lower()]
    return "\n".join(lines[:80])


def _next_steps(dotnet_available: bool, has_projects: bool) -> list[str]:
    steps = []
    if not dotnet_available:
        steps.append("Install dotnet SDK or use a C#-capable endpoint/container before running semantic diagnostics.")
    if has_projects:
        steps.append("Run code_roslyn_analysis with run=true for build diagnostics after dependencies are restored.")
        steps.append("Use code_lsp_status/code_lsp_definition when csharp-ls or OmniSharp is available for exact references.")
    return steps
