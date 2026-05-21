from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AppConfig
from .providers import chat_complete


def estimate_tokens(text: str) -> int:
    """Cheap model-agnostic approximation: ~4 chars/token for English/code-ish text."""
    return max(1, len(text) // 4)


def message_tokens(messages: list[dict[str, str]]) -> int:
    return sum(estimate_tokens(m.get("content", "")) + 4 for m in messages)


@dataclass
class ContextBudget:
    budget_tokens: int
    reserve_output_tokens: int
    history_tokens: int
    file_context_tokens: int

    @property
    def input_budget_tokens(self) -> int:
        return max(1024, self.budget_tokens - self.reserve_output_tokens)


def get_context_budget(config: AppConfig, model_name: str, context_profile: str | None) -> ContextBudget:
    model = config.models.get(model_name)
    profile = config.context_profiles.get(context_profile or "medium") or next(iter(config.context_profiles.values()), None)
    if profile is None:
        return ContextBudget(4096, 1024, 2048, 1024)
    model_ctx = model.context_window if model else profile.budget_tokens
    budget = min(model_ctx, profile.budget_tokens)
    reserve = min(profile.reserve_output_tokens, max(512, budget // 3))
    return ContextBudget(
        budget_tokens=budget,
        reserve_output_tokens=reserve,
        history_tokens=min(profile.history_tokens, max(512, budget - reserve)),
        file_context_tokens=min(profile.file_context_tokens, max(512, budget - reserve)),
    )


def _model_chunking_overrides(config: AppConfig, model_name: str | None) -> tuple[float | None, int | None]:
    model = (config.models or {}).get(model_name or "")
    if not model:
        return None, None
    chunking = (model.extra or {}).get("chunking") or {}
    fraction = chunking.get("direct_read_fraction")
    minimum_chunk_tokens = chunking.get("minimum_chunk_tokens")
    try:
        fraction_value = float(fraction) if fraction is not None else None
    except (TypeError, ValueError):
        fraction_value = None
    try:
        token_value = int(minimum_chunk_tokens) if minimum_chunk_tokens is not None else None
    except (TypeError, ValueError):
        token_value = None
    return fraction_value, token_value


def should_chunk_text(
    config: AppConfig,
    model_name: str,
    context_profile: str | None,
    text: str,
    *,
    max_fraction_of_input: float = 0.55,
) -> tuple[bool, int]:
    budget = get_context_budget(config, model_name, context_profile)
    model_fraction, model_minimum_chunk_tokens = _model_chunking_overrides(config, model_name)
    direct_read_fraction = model_fraction if model_fraction is not None else max_fraction_of_input
    minimum_chunk_tokens = max(600, model_minimum_chunk_tokens or 1200)
    usable_tokens = max(
        minimum_chunk_tokens,
        min(
            budget.file_context_tokens,
            int(budget.input_budget_tokens * max(0.2, min(direct_read_fraction, 0.9))),
        ),
    )
    return estimate_tokens(text) > usable_tokens, usable_tokens


def truncate_middle(text: str, max_tokens: int) -> str:
    if estimate_tokens(text) <= max_tokens:
        return text
    chars = max_tokens * 4
    head = max(100, chars // 2)
    tail = max(100, chars - head)
    return text[:head] + "\n\n...[context truncated in the middle]...\n\n" + text[-tail:]


def make_chunk_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:12]


def chunk_text(text: str, max_tokens: int = 1200, overlap_tokens: int = 80) -> list[dict[str, Any]]:
    max_chars = max_tokens * 4
    overlap_chars = overlap_tokens * 4
    if len(text) <= max_chars:
        return [{"id": make_chunk_id(text), "index": 0, "start": 0, "end": len(text), "content": text}]
    chunks: list[dict[str, Any]] = []
    start = 0
    idx = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        piece = text[start:end]
        chunks.append({"id": make_chunk_id(piece), "index": idx, "start": start, "end": end, "content": piece})
        if end == len(text):
            break
        start = max(0, end - overlap_chars)
        idx += 1
    return chunks


def compact_messages_basic(messages: list[dict[str, str]], budget: ContextBudget, summary: str | None = None) -> tuple[list[dict[str, str]], str | None, bool]:
    """Keep system + original user + compact older turns into a rolling summary + recent tail."""
    if message_tokens(messages) <= budget.input_budget_tokens:
        return messages, summary, False
    if len(messages) <= 4:
        compacted = []
        for i, m in enumerate(messages):
            cap = budget.input_budget_tokens // max(1, len(messages))
            compacted.append({**m, "content": truncate_middle(m.get("content", ""), cap)})
        return compacted, summary, True

    system = messages[0]
    first_user = messages[1] if len(messages) > 1 else {"role": "user", "content": ""}
    recent = messages[-8:]
    older = messages[2:-8]

    older_text = "\n\n".join(f"{m.get('role')}: {truncate_middle(m.get('content',''), 700)}" for m in older)
    new_summary = (summary or "")
    if older_text:
        new_summary = (new_summary + "\n" if new_summary else "") + "Compacted earlier agent context:\n" + truncate_middle(older_text, max(512, budget.history_tokens // 3))
        new_summary = truncate_middle(new_summary, max(512, budget.history_tokens // 2))

    compacted = [system, first_user]
    if new_summary:
        compacted.append({"role": "system", "content": new_summary})
    compacted.extend(recent)

    while message_tokens(compacted) > budget.input_budget_tokens and len(recent) > 2:
        recent = recent[2:]
        compacted = [system, first_user]
        if new_summary:
            compacted.append({"role": "system", "content": new_summary})
        compacted.extend(recent)

    if message_tokens(compacted) > budget.input_budget_tokens:
        compacted = [
            {**system, "content": truncate_middle(system.get("content", ""), budget.input_budget_tokens // 4)},
            {**first_user, "content": truncate_middle(first_user.get("content", ""), budget.input_budget_tokens // 4)},
            {"role": "system", "content": truncate_middle(new_summary or "", budget.input_budget_tokens // 4)},
        ] + [{**m, "content": truncate_middle(m.get("content", ""), budget.input_budget_tokens // 8)} for m in recent[-4:]]
    return compacted, new_summary, True


def iter_workspace_files(root: Path, max_files: int = 200) -> list[Path]:
    ignored_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".cache"}
    ignored_ext = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".gz", ".tar", ".sqlite", ".db", ".pyc"}
    files: list[Path] = []
    for p in root.rglob("*"):
        if len(files) >= max_files:
            break
        if any(part in ignored_dirs for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() not in ignored_ext:
            try:
                if p.stat().st_size <= 512_000:
                    files.append(p)
            except OSError:
                continue
    return files


def file_manifest(root: Path, max_files: int = 200) -> str:
    lines = []
    for p in iter_workspace_files(root, max_files=max_files):
        try:
            rel = p.relative_to(root)
            lines.append(f"{rel} ({p.stat().st_size} bytes)")
        except OSError:
            pass
    return "\n".join(lines)


def summarize_chunk_with_model(config: AppConfig, model: str, instruction: str, chunk: str, max_output_tokens: int = 512) -> str:
    messages = [
        {"role": "system", "content": "Summarize this chunk for a coding agent. Be compact, factual, and preserve filenames, functions, decisions, bugs, TODOs, commands, and constraints."},
        {"role": "user", "content": instruction + "\n\nCHUNK:\n" + chunk},
    ]
    try:
        return chat_complete(config, model, messages, max_tokens=max_output_tokens)
    except Exception:
        return truncate_middle(chunk, max_output_tokens)


def batch_reduce_text(config: AppConfig, model: str, instruction: str, text: str, chunk_tokens: int = 1200, final_tokens: int = 1024) -> dict[str, Any]:
    chunks = chunk_text(text, max_tokens=chunk_tokens)
    partials = []
    for c in chunks:
        partial = summarize_chunk_with_model(config, model, instruction, c["content"], max_output_tokens=512)
        partials.append({"chunk": c["index"], "id": c["id"], "summary": partial})
    combined = "\n\n".join(f"Chunk {p['chunk']} ({p['id']}):\n{p['summary']}" for p in partials)
    final = summarize_chunk_with_model(config, model, "Combine these partial summaries into one result for the original request: " + instruction, combined, max_output_tokens=final_tokens)
    return {"chunk_count": len(chunks), "partials": partials, "summary": final}
