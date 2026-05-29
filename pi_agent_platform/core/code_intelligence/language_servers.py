from __future__ import annotations

import json
import re
from dataclasses import asdict
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .scanner import CODE_EXTENSIONS, LSP_BINARIES, collect_symbols, detect_projects, find_references, iter_code_files, run_limited

INSTALL_HINTS: dict[str, list[str]] = {
    "rust": ["rustup component add rust-analyzer", "cargo install cargo-edit cargo-audit"],
    "python": ["pip install pyright python-lsp-server ruff"],
    "go": ["go install golang.org/x/tools/gopls@latest"],
    "typescript": ["npm install -g typescript typescript-language-server"],
    "csharp": ["dotnet tool install --global csharp-ls", "Install OmniSharp or ensure dotnet SDK is present"],
}

METADATA_COMMANDS: dict[str, list[str]] = {
    "rust": ["cargo", "metadata", "--format-version", "1", "--no-deps"],
    "go": ["go", "list", "-json", "./..."],
    "typescript": ["node", "-e", "const p=require('./package.json'); console.log(JSON.stringify({name:p.name,scripts:p.scripts,dependencies:p.dependencies,devDependencies:p.devDependencies}, null, 2))"],
    "python": ["python", "-c", "import json, pathlib; print(json.dumps({'pyproject': pathlib.Path('pyproject.toml').exists(), 'requirements': pathlib.Path('requirements.txt').exists()}, indent=2))"],
    "csharp": ["dotnet", "sln", "list"],
}


def language_server_status(root: Path) -> dict[str, Any]:
    projects = detect_projects(root)
    languages = set(projects.get("languages", {}).keys())
    languages.update(marker.get("language") for marker in projects.get("project_markers", []) if marker.get("language"))
    status: dict[str, Any] = {}
    for language, binaries in LSP_BINARIES.items():
        probes = []
        for binary in binaries:
            path = shutil.which(binary)
            probes.append({"binary": binary, "available": bool(path), "path": path or None})
        status[language] = {
            "detected": language in languages,
            "servers": probes,
            "ready": any(item["available"] for item in probes),
            "install_hints": INSTALL_HINTS.get(language, []),
        }
    return {"projects": projects, "language_servers": status}


def project_metadata(root: Path, *, language: str = "auto", run: bool = False, timeout: int = 30) -> dict[str, Any]:
    projects = detect_projects(root)
    languages = set(projects.get("languages", {}).keys()) if language == "auto" else {language}
    languages.update(marker.get("language") for marker in projects.get("project_markers", []) if language == "auto" and marker.get("language"))
    commands = []
    results = []
    for lang in sorted(languages):
        command = METADATA_COMMANDS.get(lang)
        if not command:
            continue
        available = bool(shutil.which(command[0]))
        commands.append({"language": lang, "command": command, "available": available})
        if run:
            results.append(run_limited(command, root, timeout=timeout) if available else {"language": lang, "command": command, "error": f"binary not found: {command[0]}"})
    return {"language": language, "projects": projects, "metadata_commands": commands, "results": results}


def _function_ranges(root: Path) -> list[dict[str, Any]]:
    symbols = [s for s in collect_symbols(root, max_files=2000) if s.kind in {"function", "method"}]
    ranges: list[dict[str, Any]] = []
    by_file: dict[str, list[Any]] = {}
    for sym in symbols:
        by_file.setdefault(sym.file, []).append(sym)
    for file, items in by_file.items():
        ordered = sorted(items, key=lambda s: s.line)
        path = root / file
        try:
            total = len(path.read_text(errors="replace").splitlines())
        except Exception:
            total = ordered[-1].line + 80 if ordered else 0
        for index, sym in enumerate(ordered):
            next_line = ordered[index + 1].line if index + 1 < len(ordered) else total + 1
            ranges.append({
                "name": sym.name,
                "kind": sym.kind,
                "language": sym.language,
                "file": sym.file,
                "start_line": sym.line,
                "end_line": max(sym.line, next_line - 1),
                "container": sym.container,
                "signature": sym.signature,
            })
    return ranges


def call_hierarchy(root: Path, symbol: str, *, max_results: int = 120) -> dict[str, Any]:
    references = find_references(root, symbol, max_results=max_results * 3).get("references", [])
    ranges = _function_ranges(root)
    callers: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    for ref in references:
        file = ref.get("file")
        line = int(ref.get("line") or 0)
        owner = next((item for item in ranges if item["file"] == file and item["start_line"] <= line <= item["end_line"]), None)
        if not owner or owner.get("name") == symbol:
            continue
        key = (str(owner["file"]), int(owner["start_line"]), str(owner["name"]))
        if key in seen:
            continue
        seen.add(key)
        callers.append({"caller": owner, "reference": ref})
        if len(callers) >= max_results:
            break
    return {"symbol": symbol, "count": len(callers), "callers": callers, "mode": "static-reference-range"}


def type_hierarchy(root: Path, symbol: str | None = None, *, max_results: int = 120) -> dict[str, Any]:
    patterns = [
        ("python", re.compile(r"^\s*class\s+(?P<name>[A-Za-z_]\w*)\s*(?:\((?P<bases>[^)]*)\))?:")),
        ("typescript", re.compile(r"^\s*(?:export\s+)?(?:class|interface)\s+(?P<name>[A-Za-z_$][\w$]*)(?:\s+extends\s+(?P<extends>[A-Za-z_$][\w$.]*))?(?:\s+implements\s+(?P<implements>[^ {]+(?:\s*,\s*[^ {]+)*))?")),
        ("csharp", re.compile(r"^\s*(?:public|private|internal|protected|abstract|sealed|partial|\s)*(?:class|interface|record)\s+(?P<name>[A-Za-z_]\w*)\s*(?::\s*(?P<bases>[^ {]+(?:\s*,\s*[^ {]+)*))?")),
        ("rust_impl", re.compile(r"^\s*impl(?:<[^>]+>)?\s+(?:(?P<trait>[A-Za-z_][\w:<>]*)\s+for\s+)?(?P<name>[A-Za-z_][\w:<>]*)")),
    ]
    entries: list[dict[str, Any]] = []
    for path in iter_code_files(root, max_files=2500):
        language = CODE_EXTENSIONS.get(path.suffix.lower())
        try:
            lines = path.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for index, line in enumerate(lines, start=1):
            for pattern_language, pattern in patterns:
                if pattern_language != "rust_impl" and pattern_language != language:
                    continue
                if pattern_language == "rust_impl" and language != "rust":
                    continue
                match = pattern.search(line)
                if not match:
                    continue
                data = match.groupdict()
                name = data.get("name") or ""
                if symbol and symbol not in {name, data.get("trait"), data.get("extends")} and symbol not in str(data.get("bases") or data.get("implements") or ""):
                    continue
                entries.append({
                    "name": name,
                    "language": "rust" if pattern_language == "rust_impl" else pattern_language,
                    "file": str(path.relative_to(root)),
                    "line": index,
                    "extends": data.get("extends"),
                    "implements": data.get("implements"),
                    "bases": data.get("bases"),
                    "trait": data.get("trait"),
                    "text": line.strip(),
                })
                if len(entries) >= max_results:
                    return {"symbol": symbol, "count": len(entries), "types": entries, "mode": "static-type-patterns"}
    return {"symbol": symbol, "count": len(entries), "types": entries, "mode": "static-type-patterns"}


def module_index(root: Path, *, language: str = "auto", max_files: int = 1200) -> dict[str, Any]:
    projects = detect_projects(root, max_files=max_files)
    modules: list[dict[str, Any]] = []
    for path in iter_code_files(root, max_files=max_files):
        lang = CODE_EXTENSIONS.get(path.suffix.lower())
        if language != "auto" and lang != language:
            continue
        rel = str(path.relative_to(root))
        module = rel.rsplit(".", 1)[0].replace("/", ".")
        if lang == "go":
            module = "/".join(rel.split("/")[:-1]) or "."
        if lang == "rust" and path.name == "mod.rs":
            module = ".".join(rel.split("/")[:-1])
        modules.append({"module": module, "language": lang, "file": rel})
    return {"language": language, "projects": projects, "count": len(modules), "modules": modules[:max_files]}


def blast_radius(root: Path, symbol: str, *, max_results: int = 200) -> dict[str, Any]:
    definitions = [s for s in collect_symbols(root, max_files=2500) if s.name == symbol]
    refs = find_references(root, symbol, max_results=max_results).get("references", [])
    files = sorted({item.file for item in definitions} | {str(ref.get("file")) for ref in refs if ref.get("file")})
    languages = sorted({item.language for item in definitions})
    return {
        "symbol": symbol,
        "definition_count": len(definitions),
        "reference_count": len(refs),
        "affected_file_count": len(files),
        "affected_files": files[:max_results],
        "definitions": [asdict(item) for item in definitions[:50]],
        "sample_references": refs[:50],
        "languages": languages,
        "recommended_validation": _validation_for_languages(languages),
        "mode": "static-symbol-reference-blast-radius",
    }


def _validation_for_languages(languages: list[str]) -> list[list[str]]:
    commands = {
        "rust": ["cargo", "check", "--message-format=json"],
        "python": ["python", "-m", "compileall", "-q", "."],
        "go": ["go", "test", "./..."],
        "typescript": ["npx", "tsc", "--noEmit"],
        "csharp": ["dotnet", "build", "--no-restore"],
    }
    return [commands[lang] for lang in languages if lang in commands]


def endpoint_script(tool: str, inp: dict[str, Any]) -> str | None:
    path = str(inp.get("path") or ".").strip() or "."
    language = str(inp.get("language") or "auto").strip().lower() or "auto"
    run = "1" if bool(inp.get("run") or False) else "0"
    timeout = max(5, min(int(inp.get("timeout") or 30), 180))
    if tool in {"code_language_servers", "code_lsp_status"}:
        body = [
            "echo '== language server availability =='",
            "for binary in rust-analyzer pyright-langserver pylsp ruff gopls typescript-language-server tsserver tsc csharp-ls omnisharp dotnet cargo go node npm npx python; do if command -v $binary >/dev/null 2>&1; then echo $binary=$(command -v $binary); else echo $binary=missing; fi; done",
            "echo '== project markers =='",
            "find . -maxdepth 4 \\( -name Cargo.toml -o -name pyproject.toml -o -name requirements.txt -o -name package.json -o -name tsconfig.json -o -name go.mod -o -name '*.csproj' -o -name '*.sln' \\) | sed 's#^./##' | sort | head -120",
        ]
    elif tool == "code_lsp_endpoint_prepare":
        body = [
            "echo '== endpoint LSP bootstrap =='",
            "mkdir -p .pac/lsp",
            "python3 - <<'PY' 2>/dev/null || true",
            "import json, pathlib, shutil, time",
            "bins = ['rust-analyzer','pyright-langserver','pylsp','gopls','typescript-language-server','tsserver','csharp-ls','omnisharp','dotnet','cargo','go','node','npm','npx','python3','python']",
            "payload = {'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'binaries': {b: shutil.which(b) for b in bins}}",
            "pathlib.Path('.pac/lsp/server-capabilities.json').write_text(json.dumps(payload, indent=2), encoding='utf-8')",
            "print(json.dumps(payload, indent=2))",
            "PY",
            "echo '== lsp cache directory =='",
            "find .pac/lsp -maxdepth 2 -type f -printf '%P\n' | sort",
        ]
    elif tool == "code_roslyn_analysis":
        body = [
            "echo '== csharp semantic readiness =='",
            "if command -v dotnet >/dev/null 2>&1; then dotnet --info | head -80; else echo dotnet=missing; fi",
            "echo '== csharp projects =='",
            "find . -maxdepth 5 \\( -name '*.sln' -o -name '*.csproj' -o -name '*.cs' \\) | sed 's#^./##' | sort | head -300",
            "if [ \"$RUN\" = 1 ] && command -v dotnet >/dev/null 2>&1; then echo '== dotnet build diagnostics =='; timeout \"$TIMEOUT\" dotnet build --no-restore --nologo || true; fi",
        ]
    elif tool == "code_project_metadata":
        body = [
            "echo '== project metadata =='",
            "if { [ \"$LANGUAGE\" = auto ] || [ \"$LANGUAGE\" = rust ]; } && [ -f Cargo.toml ] && command -v cargo >/dev/null 2>&1; then echo '--- cargo metadata ---'; timeout \"$TIMEOUT\" cargo metadata --format-version 1 --no-deps || true; fi",
            "if { [ \"$LANGUAGE\" = auto ] || [ \"$LANGUAGE\" = go ]; } && [ -f go.mod ] && command -v go >/dev/null 2>&1; then echo '--- go list ---'; timeout \"$TIMEOUT\" go list -json ./... || true; fi",
            "if { [ \"$LANGUAGE\" = auto ] || [ \"$LANGUAGE\" = typescript ]; } && [ -f package.json ] && command -v node >/dev/null 2>&1; then echo '--- package.json summary ---'; node -e \"const p=require('./package.json'); console.log(JSON.stringify({name:p.name,scripts:p.scripts,dependencies:p.dependencies,devDependencies:p.devDependencies}, null, 2))\" || true; fi",
            "if { [ \"$LANGUAGE\" = auto ] || [ \"$LANGUAGE\" = csharp ]; } && command -v dotnet >/dev/null 2>&1; then echo '--- dotnet projects ---'; dotnet sln list 2>/dev/null || find . -maxdepth 4 -name '*.csproj' -print; fi",
            "if { [ \"$LANGUAGE\" = auto ] || [ \"$LANGUAGE\" = python ]; }; then echo '--- python markers ---'; find . -maxdepth 3 \\( -name pyproject.toml -o -name requirements.txt -o -name setup.py \\) -print | sort; fi",
        ]
    else:
        return None
    lines = ["set -eu", f"LANGUAGE='{language}'", f"RUN={run}", f"TIMEOUT={timeout}"] + body
    quoted = "'" + path.replace("'", "'\\''") + "'"
    script = "\n".join(lines).replace("'", "'\\''")
    return f"cd {quoted} 2>/dev/null || exit 2; sh -lc '{script}'"
