"""Workspace lessons — persistent cross-session memory accumulated per project."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from .pac_ram import read_ram, write_ram

# Max entries to keep in the active lessons before aging out old ones
MAX_LESSONS = 200


def _sanitize(text: str, max_chars: int = 3000) -> str:
    """Trim and clean text."""
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    return text


def _slug(text: str) -> str:
    """Make a URL-safe slug from arbitrary text."""
    text = text.lower().replace(" ", "-").replace("/", "-").replace("\\", "-")
    text = re.sub(r"[^a-z0-9.-]", "", text)
    return text[:60]


def save_lesson(
    workspace_path: str,
    category: str,
    title: str,
    body: str,
    tags: list[str] | None = None,
    tool_calls: list[dict] | None = None,
    files_touched: list[str] | None = None,
    commit_hash: str | None = None,
) -> dict[str, Any]:
    """
    Save a lesson to the workspace's pac_ram workspace memory.
    Appends as a structured entry to the workspace's PAC-RAM file.
    
    Args:
        workspace_path: the workspace root (e.g. /home/node/.pacp/workspaces/abc)
        category: one of "implementation", "discovery", "decision", "risk", "convention", "task_result"
        title: short label (max 100 chars)
        body: detailed description (max 3000 chars)
        tags: arbitrary labels for search
        tool_calls: list of {tool, input, observation} dicts from the session
        files_touched: list of file paths modified or read
        commit_hash: git hash if code was committed
    
    Returns:
        {"ok": True, "lesson_id": "..."}
    """
    kind = "workspace"
    # Use workspace dir name + "lessons" as the key
    ws_name = Path(workspace_path).name
    key = f"{ws_name}-lessons"
    
    # Read existing RAM content
    record = read_ram(kind, key)
    existing = record.get("content", "") if record.get("exists") else ""
    
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    lesson_id = f"{now[:10]}-{_slug(title)[:40]}"
    
    # Build lesson entry
    lines = [
        f"\n--- LESSON {lesson_id} ---",
        f"category: {category}",
        f"title: {title}",
        f"saved_at: {now}",
        f"workspace: {workspace_path}",
    ]
    
    if tags:
        lines.append(f"tags: {', '.join(tags)}")
    
    if files_touched:
        unique_files = list(dict.fromkeys(files_touched))  # dedupe preserve order
        lines.append(f"files_touched: {', '.join(unique_files[:20])}")
    
    if commit_hash:
        lines.append(f"commit: {commit_hash}")
    
    if tool_calls:
        lines.append("tool_sequence:")
        for tc in tool_calls[-8:]:  # last 8 tool calls
            tool_name = tc.get("tool", "?")
            inp = str(tc.get("input", {}))[:200]
            obs = str(tc.get("observation", ""))[:300]
            lines.append(f"  - tool: {tool_name}")
            lines.append(f"    input: {inp}")
            lines.append(f"    observation: {obs[:300]}")
    
    lines.append(f"body: |")
    for body_line in body.strip().split("\n"):
        lines.append(f"  {body_line}")
    
    lines.append("---")
    
    new_entry = "\n".join(lines)
    new_content = existing + new_entry
    
    # Enforce MAX_LESSONS by trimming oldest entries from the top
    if new_content.count("--- LESSON") > MAX_LESSONS:
        # Keep only the last MAX_LESSONS entries
        all_entries = new_content.split("--- LESSON ")
        if len(all_entries) > MAX_LESSONS:
            trimmed = all_entries[-MAX_LESSONS:]
            new_content = "--- LESSON ".join(trimmed)
    
    result = write_ram(kind, key, new_content)
    result["lesson_id"] = lesson_id
    return result


def load_lessons(workspace_path: str, category: str | None = None, limit: int = 30) -> dict[str, Any]:
    """Load recent lessons for a workspace, optionally filtered by category."""
    kind = "workspace"
    ws_name = Path(workspace_path).name
    key = f"{ws_name}-lessons"
    record = read_ram(kind, key)
    
    if not record.get("exists") or not record.get("content"):
        return {"lessons": [], "count": 0, "workspace": workspace_path}
    
    content = record["content"]
    
    # Parse lessons from content
    lessons = []
    current = {}
    current_lines = []
    in_body = False
    
    for raw_line in content.split("\n"):
        line = raw_line.rstrip()
        
        if line.startswith("--- LESSON "):
            if current and current.get("title"):
                current["body"] = "\n".join(current_lines).strip()
                lessons.append(current)
            slug_id = line.replace("--- LESSON ", "").strip()
            current = {"lesson_id": slug_id, "category": "", "title": "", "saved_at": "", "tags": [], "files_touched": [], "tool_sequence": [], "body": ""}
            current_lines = []
            in_body = False
        elif current and line.startswith("category: "):
            current["category"] = line.replace("category: ", "")
        elif current and line.startswith("title: "):
            current["title"] = line.replace("title: ", "")
        elif current and line.startswith("saved_at: "):
            current["saved_at"] = line.replace("saved_at: ", "")
        elif current and line.startswith("tags: "):
            current["tags"] = [t.strip() for t in line.replace("tags: ", "").split(",") if t.strip()]
        elif current and line.startswith("files_touched: "):
            current["files_touched"] = [f.strip() for f in line.replace("files_touched: ", "").split(",") if f.strip()]
        elif current and line.startswith("commit: "):
            current["commit"] = line.replace("commit: ", "")
        elif current and line.startswith("tool_sequence:"):
            pass
        elif current and line.startswith("  - tool: "):
            tool_name = line.replace("  - tool: ", "")
            if "tool_sequence" not in current:
                current["tool_sequence"] = []
            current["tool_sequence"].append({"tool": tool_name})
        elif current and current.get("tool_sequence") and line.startswith("    input: "):
            current["tool_sequence"][-1]["input"] = line.replace("    input: ", "")
        elif current and current.get("tool_sequence") and line.startswith("    observation: "):
            current["tool_sequence"][-1]["observation"] = line.replace("    observation: ", "")
        elif current and line.startswith("body: |"):
            in_body = True
        elif in_body and line.startswith("  ") and not line.startswith("---"):
            current_lines.append(line[2:])
        elif current and line == "---":
            in_body = False
    
    # Don't forget the last one
    if current and current.get("title"):
        current["body"] = "\n".join(current_lines).strip()
        lessons.append(current)
    
    # Filter by category
    if category:
        lessons = [l for l in lessons if l.get("category") == category]
    
    return {
        "lessons": lessons[-limit:],
        "count": len(lessons),
        "total_indexed": len(lessons),
        "workspace": workspace_path,
    }


def search_lessons(workspace_path: str, query: str, category: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Full-text search across lessons."""
    needle = str(query or "").strip().lower()
    if not needle:
        return {"results": [], "query": query}
    
    data = load_lessons(workspace_path, category=category, limit=200)
    results = []
    
    for lesson in data.get("lessons", []):
        haystack = f"{lesson.get('title', '')} {lesson.get('body', '')} {lesson.get('category', '')}".lower()
        if needle not in haystack:
            continue
        
        # Get snippet
        body = lesson.get("body", "")
        idx = body.lower().find(needle)
        start = max(0, idx - 150)
        end = min(len(body), idx + len(needle) + 200)
        snippet = body[start:end].strip()
        
        results.append({
            "lesson_id": lesson.get("lesson_id"),
            "category": lesson.get("category"),
            "title": lesson.get("title"),
            "snippet": snippet,
            "saved_at": lesson.get("saved_at"),
            "files_touched": lesson.get("files_touched", [])[:5],
        })
        
        if len(results) >= limit:
            break
    
    return {"query": query, "results": results, "count": len(results)}


def get_project_memory(workspace_path: str) -> dict[str, Any]:
    """Load full project memory summary for a workspace — used to inject context on session start."""
    data = load_lessons(workspace_path, limit=20)
    lessons = data.get("lessons", [])
    
    if not lessons:
        return {"has_memory": False, "lessons": [], "summary": ""}
    
    # Build a compact summary by category
    by_category = {}
    for lesson in lessons:
        cat = lesson.get("category", "other")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(lesson["title"])
    
    summary_parts = []
    for cat, titles in by_category.items():
        summary_parts.append(f"  {cat}: {', '.join(titles[:5])}")
    
    summary = "Workspace project memory (recent lessons):\n" + "\n".join(summary_parts)
    
    return {
        "has_memory": True,
        "count": data["count"],
        "by_category": by_category,
        "summary": summary,
    }