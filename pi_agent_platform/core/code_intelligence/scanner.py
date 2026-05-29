from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "target", "dist", "build", ".mypy_cache", ".pytest_cache"}
CODE_EXTENSIONS = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
}
PROJECT_MARKERS = {
    "Cargo.toml": "rust",
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "package.json": "typescript",
    "tsconfig.json": "typescript",
    "go.mod": "go",
    ".csproj": "csharp",
    ".sln": "csharp",
}
LSP_BINARIES = {
    "rust": ["rust-analyzer"],
    "python": ["pyright-langserver", "pylsp", "ruff"],
    "go": ["gopls"],
    "typescript": ["typescript-language-server", "tsserver", "tsc"],
    "csharp": ["csharp-ls", "omnisharp", "dotnet"],
}


@dataclass(slots=True)
class Symbol:
    name: str
    kind: str
    language: str
    file: str
    line: int
    container: str | None = None
    signature: str | None = None


def safe_root(workspace: str | Path, rel_path: str | None = None) -> Path:
    root = Path(workspace).resolve()
    target = (root / (rel_path or ".")).resolve()
    if root != target and root not in target.parents:
        raise ValueError("Path escapes workspace")
    return target


def iter_code_files(root: Path, *, max_files: int = 1200) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if len(files) >= max_files:
            break
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix.lower() in CODE_EXTENSIONS:
            files.append(path)
    return files


def detect_projects(root: Path, *, max_files: int = 2500) -> dict[str, Any]:
    markers: list[dict[str, str]] = []
    languages: dict[str, int] = {}
    files_scanned = 0
    for path in root.rglob("*"):
        if files_scanned >= max_files:
            break
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        files_scanned += 1
        rel = str(path.relative_to(root))
        language = CODE_EXTENSIONS.get(path.suffix.lower())
        if language:
            languages[language] = languages.get(language, 0) + 1
        marker_language = PROJECT_MARKERS.get(path.name)
        if not marker_language and path.suffix.lower() in {".csproj", ".sln"}:
            marker_language = "csharp"
        if marker_language:
            markers.append({"path": rel, "language": marker_language})
    return {"root": str(root), "languages": languages, "project_markers": markers[:100], "files_scanned": files_scanned}


def lsp_status() -> dict[str, list[dict[str, Any]]]:
    status: dict[str, list[dict[str, Any]]] = {}
    for language, binaries in LSP_BINARIES.items():
        status[language] = [{"binary": binary, "available": bool(shutil.which(binary))} for binary in binaries]
    return status


def _line_text(path: Path, line: int) -> str:
    try:
        lines = path.read_text(errors="replace").splitlines()
        if 1 <= line <= len(lines):
            return lines[line - 1].strip()
    except Exception:
        pass
    return ""


def _python_symbols(path: Path, root: Path) -> list[Symbol]:
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except Exception:
        return []
    symbols: list[Symbol] = []
    containers: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            symbols.append(Symbol(node.name, "class", "python", str(path.relative_to(root)), node.lineno, containers[-1] if containers else None, _line_text(path, node.lineno)))
            containers.append(node.name)
            self.generic_visit(node)
            containers.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            kind = "method" if containers else "function"
            symbols.append(Symbol(node.name, kind, "python", str(path.relative_to(root)), node.lineno, containers[-1] if containers else None, _line_text(path, node.lineno)))
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

    Visitor().visit(tree)
    return symbols


REGEX_RULES: dict[str, list[tuple[str, str]]] = {
    "typescript": [
        ("class", r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)"),
        ("interface", r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)"),
        ("type", r"^\s*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)"),
        ("function", r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"),
        ("function", r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("),
    ],
    "go": [("function", r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"), ("type", r"^\s*type\s+([A-Za-z_]\w*)\s+")],
    "rust": [
        ("function", r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)"),
        ("struct", r"^\s*(?:pub\s+)?struct\s+([A-Za-z_]\w*)"),
        ("enum", r"^\s*(?:pub\s+)?enum\s+([A-Za-z_]\w*)"),
        ("trait", r"^\s*(?:pub\s+)?trait\s+([A-Za-z_]\w*)"),
        ("module", r"^\s*(?:pub\s+)?mod\s+([A-Za-z_]\w*)"),
        ("impl", r"^\s*impl(?:<[^>]+>)?\s+([^\s{]+)"),
    ],
    "csharp": [
        ("class", r"^\s*(?:public|private|internal|protected|static|sealed|abstract|partial|\s)*\s*class\s+([A-Za-z_]\w*)"),
        ("interface", r"^\s*(?:public|private|internal|protected|partial|\s)*\s*interface\s+([A-Za-z_]\w*)"),
        ("record", r"^\s*(?:public|private|internal|protected|partial|\s)*\s*record\s+([A-Za-z_]\w*)"),
        ("method", r"^\s*(?:public|private|internal|protected|static|async|virtual|override|sealed|\s)+[A-Za-z_][\w<>?,\[\]\s]*\s+([A-Za-z_]\w*)\s*\("),
    ],
}


def _regex_symbols(path: Path, root: Path, language: str) -> list[Symbol]:
    rules = REGEX_RULES.get(language, [])
    symbols: list[Symbol] = []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except Exception:
        return symbols
    for index, line in enumerate(lines, start=1):
        for kind, pattern in rules:
            match = re.search(pattern, line)
            if match:
                symbols.append(Symbol(match.group(1).strip(), kind, language, str(path.relative_to(root)), index, None, line.strip()))
                break
    return symbols


def collect_symbols(root: Path, *, max_files: int = 1200) -> list[Symbol]:
    symbols: list[Symbol] = []
    for path in iter_code_files(root, max_files=max_files):
        language = CODE_EXTENSIONS.get(path.suffix.lower())
        if language == "python":
            symbols.extend(_python_symbols(path, root))
        elif language:
            symbols.extend(_regex_symbols(path, root, language))
    return symbols


def search_symbols(root: Path, query: str, *, language: str | None = None, kind: str | None = None, max_results: int = 80) -> dict[str, Any]:
    query_lower = query.strip().lower()
    matches: list[dict[str, Any]] = []
    for symbol in collect_symbols(root):
        if language and symbol.language != language:
            continue
        if kind and symbol.kind != kind:
            continue
        if not query_lower or query_lower in symbol.name.lower():
            matches.append(asdict(symbol))
        if len(matches) >= max_results:
            break
    return {"query": query, "language": language, "kind": kind, "count": len(matches), "symbols": matches}


def find_references(root: Path, symbol: str, *, max_results: int = 120) -> dict[str, Any]:
    pattern = re.compile(r"\b" + re.escape(symbol) + r"\b")
    refs: list[dict[str, Any]] = []
    for path in iter_code_files(root, max_files=2000):
        try:
            lines = path.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for index, line in enumerate(lines, start=1):
            if pattern.search(line):
                refs.append({"file": str(path.relative_to(root)), "line": index, "text": line.strip()})
                if len(refs) >= max_results:
                    return {"symbol": symbol, "count": len(refs), "references": refs}
    return {"symbol": symbol, "count": len(refs), "references": refs}


def run_limited(command: list[str], cwd: Path, *, timeout: int = 30) -> dict[str, Any]:
    try:
        proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return {"command": command, "exit_code": proc.returncode, "stdout": proc.stdout[-12000:], "stderr": proc.stderr[-8000:]}
    except FileNotFoundError:
        return {"command": command, "error": f"binary not found: {command[0]}"}
    except subprocess.TimeoutExpired as exc:
        return {"command": command, "error": f"timed out after {timeout}s", "stdout": (exc.stdout or "")[-4000:], "stderr": (exc.stderr or "")[-4000:]}


def diagnostics(root: Path, language: str = "auto", *, run: bool = False, timeout: int = 30) -> dict[str, Any]:
    projects = detect_projects(root)
    languages = set(projects.get("languages", {}).keys()) if language == "auto" else {language}
    suggestions: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    command_by_language = {
        "rust": ["cargo", "check", "--message-format=json"],
        "python": ["python", "-m", "compileall", "-q", "."],
        "go": ["go", "test", "./..."],
        "typescript": ["npx", "tsc", "--noEmit"],
        "csharp": ["dotnet", "build", "--no-restore"],
    }
    for lang in sorted(languages):
        command = command_by_language.get(lang)
        if not command:
            continue
        available = bool(shutil.which(command[0]))
        suggestions.append({"language": lang, "command": command, "available": available})
        if run:
            results.append(run_limited(command, root, timeout=timeout) if available else {"command": command, "error": f"binary not found: {command[0]}"})
    return {"language": language, "run": run, "suggested_diagnostics": suggestions, "results": results}


def report(root: Path, *, max_files: int = 1200) -> dict[str, Any]:
    projects = detect_projects(root, max_files=max_files)
    symbols = collect_symbols(root, max_files=max_files)
    by_language: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for symbol in symbols:
        by_language[symbol.language] = by_language.get(symbol.language, 0) + 1
        by_kind[symbol.kind] = by_kind.get(symbol.kind, 0) + 1
    return {
        "projects": projects,
        "lsp": lsp_status(),
        "symbol_index": {"total": len(symbols), "by_language": by_language, "by_kind": by_kind, "sample": [asdict(s) for s in symbols[:80]]},
    }
