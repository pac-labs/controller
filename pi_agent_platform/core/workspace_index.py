"""Workspace indexing — builds a structured project snapshot on session start."""
import fnmatch
import json
import subprocess
from pathlib import Path
from typing import Any


def build_workspace_index(root: Path, max_files: int = 600) -> dict[str, Any]:
    """
    Build a comprehensive project index for a workspace.
    Returns a structured dict with: tree, project_type, projects, key_files,
    python_symbols, git_summary, file_count, total_bytes.
    """
    if not root.exists():
        return {"error": f"Workspace not found: {root}"}

    result = {
        "workspace": str(root),
        "project_type": detect_project_type(root),
        "projects": detect_projects(root),
        "tree": build_file_tree(root, max_files=max_files),
        "key_files": index_key_files(root),
        "python_symbols": index_python_symbols(root, max_files=300),
        "git_summary": get_git_summary(root),
    }
    return result


def detect_project_type(root: Path) -> str:
    """Return 'python', 'node', 'rust', 'go', 'java', 'dotnet', 'unknown' based on lockfiles."""
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists() or (root / "requirements.txt").exists():
        return "python"
    if (root / "package.json").exists():
        return "node"
    if (root / "Cargo.toml").exists():
        return "rust"
    if (root / "go.mod").exists():
        return "go"
    if (root / "pom.xml").exists() or (root / "build.gradle").exists():
        return "java"
    if (root / "*.csproj").exists() or (root / "*.sln").exists():
        return "dotnet"
    return "unknown"


def detect_projects(root: Path) -> list[dict]:
    """Find all project roots (where lockfile or package file lives)."""
    projects = []
    checks = {
        "python": ["pyproject.toml", "requirements.txt", "setup.py", "Pipfile", "poetry.lock"],
        "node": ["package.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb"],
        "rust": ["Cargo.toml"],
        "go": ["go.mod"],
        "java": ["pom.xml", "build.gradle"],
        "dotnet": ["*.csproj"],
    }
    for ptype, files in checks.items():
        for f in files:
            if "*." in f:  # glob pattern — skip for simple exists() check
                continue
            path = root / f
            if path.exists():
                projects.append({"type": ptype, "root": str(path.parent), "file": f})
    return projects


def build_file_tree(root: Path, max_files: int = 600) -> dict:
    """
    Build a nested dict tree of the directory structure.
    Keys are dir names; files are stored with 'type: file' and size.
    Skips: .git, node_modules, __pycache__, .venv, .pytest_cache, .mypy_cache, .ruff_cache, dist, build, target, .idea, .vscode
    Returns a nested dict.
    """
    SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build", "target", ".idea", ".vscode", ".tox", ".nox", "vendor", "Godeps"}

    tree = {}
    count = [0]
    total_bytes = [0]

    def walk(dir_path: Path, node: dict):
        if count[0] >= max_files:
            return
        try:
            for child in sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                name = child.name
                if name in SKIP_DIRS:
                    continue
                if count[0] >= max_files:
                    return
                if child.is_dir():
                    node[name] = {"type": "dir", "children": {}}
                    walk(child, node[name]["children"])
                else:
                    try:
                        size = child.stat().st_size
                    except Exception:
                        size = 0
                    total_bytes[0] += size
                    node[name] = {"type": "file", "size": size}
                    count[0] += 1
        except PermissionError:
            pass

    walk(root, tree)
    return {"root": tree, "file_count": count[0], "total_bytes": total_bytes[0]}


def index_key_files(root: Path) -> list[dict]:
    """Find README files, configs, entrypoints, Dockerfiles, CI files."""
    key_patterns = [
        "README*", "readme*", "CONTRIBUTING*", "CHANGELOG*", "LICENSE*",
        "Dockerfile*", ".dockerignore",
        ".env*", ".env.example*",
        "docker-compose*", "docker-compose.yml", "docker-compose.yaml",
        ".gitignore", ".gitattributes",
        "Makefile", "Taskfile*", "justfile",
        "pyproject.toml", "setup.py", "setup.cfg", "requirements*.txt", "Pipfile", "poetry.lock",
        "package.json", "tsconfig.json", "next.config.*", "vite.config.*",
        "Cargo.toml", "rust-toolchain.toml",
        "go.mod", "go.sum",
        ".eslintrc*", ".prettierrc*", "eslint.config.*", "prettier.config.*",
        "pytest.ini", "tox.ini", "mypy.ini", "ruff.toml", ".ruff.toml",
        ".github/**/*.yml", ".github/**/*.yaml",
        "mkdocs.yml", "docs/**/*.md",
    ]
    found = []
    for pattern in key_patterns:
        if "*" in pattern:
            for p in root.rglob(pattern):
                if len(found) >= 50:
                    break
                rel = str(p.relative_to(root))
                try:
                    content = p.read_text(errors="replace", encoding="utf-8")[:500]
                except Exception:
                    content = ""
                found.append({"path": rel, "role": categorize_path(rel), "preview": content[:200]})
        else:
            p = root / pattern
            if p.exists() and p.is_file():
                try:
                    content = p.read_text(errors="replace", encoding="utf-8")[:500]
                except Exception:
                    content = ""
                found.append({"path": pattern, "role": categorize_path(pattern), "preview": content[:200]})
    return found[:30]


def categorize_path(path: str) -> str:
    """Label what kind of file this is."""
    p = path.lower()
    if "readme" in p:
        return "documentation"
    if "changelog" in p:
        return "changelog"
    if "license" in p:
        return "license"
    if "dockerfile" in p:
        return "container_config"
    if "docker-compose" in p:
        return "container_compose"
    if "requirements" in p or "pyproject" in p or "pipfile" in p or "poetry" in p:
        return "dependency_manifest"
    if "package.json" in p:
        return "dependency_manifest"
    if "cargo" in p or "rust" in p:
        return "dependency_manifest"
    if "go.mod" in p:
        return "dependency_manifest"
    if ".env" in p:
        return "environment_config"
    if ".gitignore" in p or ".gitattributes" in p:
        return "git_config"
    if "makefile" in p or "taskfile" in p or "justfile" in p:
        return "build_runner"
    if "pytest" in p or "tox" in p or "mypy" in p or "ruff" in p:
        return "quality_config"
    if ".eslint" in p or ".prettier" in p:
        return "code_quality"
    if "mkdocs" in p or "/docs/" in p:
        return "documentation"
    if ".github/" in p:
        return "ci_config"
    return "config"


def index_python_symbols(root: Path, max_files: int = 300) -> list[dict]:
    """Find top-level defs and classes in Python files."""
    symbols = []
    seen = set()
    for py_file in root.rglob("*.py"):
        if "test" in str(py_file) or str(py_file) in seen:
            continue
        seen.add(str(py_file))
        if len(symbols) >= max_files:
            break
        try:
            lines = py_file.read_text(errors="replace").split("\n")
        except Exception:
            continue
        rel = str(py_file.relative_to(root))
        file_symbols = {"file": rel, "defs": [], "classes": []}
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("def ") and "self" not in stripped and "cls" not in stripped:
                name = stripped.split("(")[0].replace("def ", "")
                file_symbols["defs"].append({"name": name, "line": i + 1})
            elif stripped.startswith("class "):
                name = stripped.split("(")[0].replace("class ", "").replace(":", "")
                file_symbols["classes"].append({"name": name, "line": i + 1})
        if file_symbols["defs"] or file_symbols["classes"]:
            symbols.append(file_symbols)
    return symbols


def get_git_summary(root: Path, max_commits: int = 10) -> dict:
    """Get recent git history, files changed, line diff summary."""
    if not (root / ".git").exists():
        return {"error": "not a git repo"}

    def run_git(args: list[str], cwd: Path = root) -> str:
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    # Last N commits
    log_lines = run_git(["log", f"--format=%H|%an|%ai|%s", f"-n{max_commits}"]).split("\n")
    commits = []
    for line in log_lines:
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) == 4:
            commits.append({"hash": parts[0][:8], "author": parts[1], "date": parts[2], "message": parts[3]})

    # Files changed in last commit
    last_commit = run_git(["log", "-1", "--name-status", "HEAD"]).split("\n")
    changed_files = []
    for line in last_commit[1:]:
        if line.strip() and "\t" in line:
            status, filepath = line.split("\t", 1)
            changed_files.append({"status": status.strip(), "path": filepath.strip()})

    # Total commits, branches
    total = run_git(["rev-list", "--count", "HEAD"])
    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"])

    # Diff stats (lines added/removed) for last commit
    diff_stat = run_git(["diff", "--stat", "HEAD~1..HEAD"]) if commits else ""

    return {
        "repo": root.name,
        "branch": branch,
        "total_commits": int(total) if total.isdigit() else 0,
        "recent_commits": commits,
        "last_commit_changed": changed_files[:20],
        "diff_stat": diff_stat[:300],
    }
