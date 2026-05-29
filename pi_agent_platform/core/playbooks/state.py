from __future__ import annotations

from pathlib import Path

from ..platform_home import pacp_path
from .schema import PlaybookRun


def runs_dir() -> Path:
    path = pacp_path("playbook-runs")
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_path(run_id: str) -> Path:
    return runs_dir() / f"{run_id}.json"


def save_run(run: PlaybookRun) -> PlaybookRun:
    run.touch()
    path = run_path(run.id)
    path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    return run


def load_run(run_id: str) -> PlaybookRun | None:
    path = run_path(run_id)
    if not path.exists():
        return None
    return PlaybookRun.model_validate_json(path.read_text(encoding="utf-8"))


def list_runs(limit: int = 100) -> list[PlaybookRun]:
    files = sorted(runs_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[: max(1, limit)]
    runs: list[PlaybookRun] = []
    for path in files:
        try:
            runs.append(PlaybookRun.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return runs
