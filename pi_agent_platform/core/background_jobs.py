"""Background shell job tracker — persists across tool calls."""
from __future__ import annotations
import asyncio
import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JOBS: dict[str, dict] = {}

@dataclass
class BackgroundJob:
    id: str
    command: str
    cwd: str
    started_at: float
    status: str = "running"  # running | completed | failed | stopped
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    pid: int | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "command": self.command,
            "cwd": self.cwd,
            "started_at": self.started_at,
            "status": self.status,
            "returncode": self.returncode,
            "pid": self.pid,
            "stdout": self.stdout[-8000:],
            "stderr": self.stderr[-2000:],
            "age_seconds": round(time.time() - self.started_at, 1),
        }

async def start_job(job_id: str, command: str, cwd: str) -> BackgroundJob:
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    job = BackgroundJob(id=job_id, command=command, cwd=cwd, started_at=time.time(), pid=proc.pid)
    JOBS[job_id] = job
    # Consume stdout/stderr in background
    async def consumestdout():
        try:
            out = await proc.communicate()
            job.stdout = out[0].decode(errors="replace") if out[0] else ""
            job.stderr = out[1].decode(errors="replace") if out[1] else ""
            job.returncode = proc.returncode
            job.status = "completed" if proc.returncode == 0 else "failed"
        except Exception:
            job.status = "failed"
    asyncio.create_task(consumestdout())
    return job

def get_job(job_id: str) -> BackgroundJob | None:
    return JOBS.get(job_id)

def list_jobs() -> list[dict]:
    return [j.to_dict() for j in JOBS.values()]

def stop_job(job_id: str) -> bool:
    job = JOBS.get(job_id)
    if not job:
        return False
    try:
        import os, signal
        os.kill(job.pid, signal.SIGTERM)
        job.status = "stopped"
    except Exception:
        try:
            import os, signal
            os.kill(job.pid, signal.SIGKILL)
            job.status = "stopped"
        except Exception:
            return False
    return True

def cleanup_old_jobs(max_age_seconds: float = 3600) -> int:
    """Remove jobs older than max_age_seconds."""
    now = time.time()
    to_remove = [jid for jid, j in JOBS.items() if now - j.started_at > max_age_seconds]
    for jid in to_remove:
        del JOBS[jid]
    return len(to_remove)
