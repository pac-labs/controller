"""Session/task checkpoint — lightweight state snapshots on disk for crash recovery."""
from __future__ import annotations
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .platform_home import pacp_path

CHECKPOINT_DIR = pacp_path("checkpoints")
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

# Max checkpoints to keep per session (last N)
MAX_CHECKPOINTS = 5


@dataclass
class SessionCheckpoint:
    session_id: str
    task_id: str
    checkpoint_at: float
    checkpoint_seq: int  # monotonic counter per session
    session_status: str
    task_status: str
    step: int
    rolling_summary: str
    messages_count: int
    transcript_len: int
    workspace_path: str
    agent_profile: str
    model: str
    prompt: str
    output: str
    metadata_keys: list[str]  # what keys are in task.metadata


def save_checkpoint(
    session_id: str,
    task_id: str,
    step: int,
    rolling_summary: str,
    messages: list[dict],
    transcript: list[dict],
    workspace_path: str,
    agent_profile: str,
    model: str,
    prompt: str,
    output: str,
    task_status: str,
    session_status: str,
    metadata: dict[str, Any],
) -> str:
    """
    Save a lightweight session checkpoint to disk.
    Returns the checkpoint path.
    """
    # Get next seq number
    session_dir = CHECKPOINT_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    existing = list(session_dir.glob("checkpoint_*.json"))
    seq = len(existing) + 1

    checkpoint = SessionCheckpoint(
        session_id=session_id,
        task_id=task_id,
        checkpoint_at=time.time(),
        checkpoint_seq=seq,
        session_status=session_status,
        task_status=task_status,
        step=step,
        rolling_summary=rolling_summary[:2000] if rolling_summary else "",
        messages_count=len(messages),
        transcript_len=len(transcript),
        workspace_path=workspace_path,
        agent_profile=agent_profile,
        model=model,
        prompt=prompt[:1000] if prompt else "",
        output=output[:2000] if output else "",
        metadata_keys=list(metadata.keys()),
    )

    path = session_dir / f"checkpoint_{seq:04d}.json"
    path.write_text(json.dumps(asdict(checkpoint), indent=2), encoding="utf-8")

    # Trim old checkpoints
    all_checkpoints = sorted(session_dir.glob("checkpoint_*.json"), key=lambda p: p.stat().st_mtime)
    for old_cp in all_checkpoints[:-MAX_CHECKPOINTS]:
        old_cp.unlink()

    return str(path)


def load_latest_checkpoint(session_id: str) -> SessionCheckpoint | None:
    """Load the most recent checkpoint for a session, or None."""
    session_dir = CHECKPOINT_DIR / session_id
    if not session_dir.exists():
        return None
    checkpoints = sorted(session_dir.glob("checkpoint_*.json"), key=lambda p: p.stat().st_mtime)
    if not checkpoints:
        return None
    try:
        data = json.loads(checkpoints[-1].read_text(encoding="utf-8"))
        return SessionCheckpoint(**data)
    except Exception:
        return None


def list_checkpoints(session_id: str) -> list[dict]:
    """List all checkpoints for a session."""
    session_dir = CHECKPOINT_DIR / session_id
    if not session_dir.exists():
        return []
    checkpoints = sorted(session_dir.glob("checkpoint_*.json"), key=lambda p: p.stat().st_mtime)
    result = []
    for cp_path in checkpoints:
        try:
            data = json.loads(cp_path.read_text(encoding="utf-8"))
            result.append({
                "seq": data.get("checkpoint_seq"),
                "at": datetime.fromtimestamp(data.get("checkpoint_at", 0), timezone.utc).isoformat().replace("+00:00", "Z"),
                "step": data.get("step"),
                "task_status": data.get("task_status"),
                "transcript_len": data.get("transcript_len"),
                "path": str(cp_path),
            })
        except Exception:
            continue
    return result


def delete_checkpoints(session_id: str) -> int:
    """Delete all checkpoints for a session. Returns count deleted."""
    session_dir = CHECKPOINT_DIR / session_id
    if not session_dir.exists():
        return 0
    count = len(list(session_dir.glob("checkpoint_*.json")))
    for f in session_dir.glob("checkpoint_*.json"):
        f.unlink()
    return count