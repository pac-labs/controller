#!/usr/bin/env python3
"""Report PAC codebase pressure points.

This lightweight check is intentionally read-only. It helps release authors and
agents see whether the known monolith files are shrinking or growing while the
refactor is in progress.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class PressurePoint:
    path: str
    budget: int
    reason: str


PRESSURE_POINTS: tuple[PressurePoint, ...] = (
    PressurePoint("pi_agent_platform/web/app.js", 700, "web UI logic should be split by feature"),
    PressurePoint("pi_agent_platform/api/main.py", 700, "API entrypoint should become app bootstrap and router registration"),
    PressurePoint("pi_agent_platform/web/styles.css", 700, "styles should be split into tokens, layout, components, pages, and themes"),
    PressurePoint("pi_agent_platform/core/agent_loop.py", 700, "agent runtime should be split into planner/parser/router/executor modules"),
    PressurePoint("pi_agent_platform/core/source_library.py", 700, "source library should be split into paths/tree/files/archives/builds modules"),
)


def count_lines(path: Path) -> int:
    if not path.exists():
        return -1
    return sum(1 for _ in path.open("r", encoding="utf-8", errors="replace"))


def render_markdown(root: Path, points: Iterable[PressurePoint]) -> str:
    rows = ["| File | Lines | Budget | Over budget | Reason |", "|---|---:|---:|---:|---|"]
    for point in points:
        lines = count_lines(root / point.path)
        over = "missing" if lines < 0 else max(0, lines - point.budget)
        display_lines = "missing" if lines < 0 else str(lines)
        rows.append(f"| `{point.path}` | {display_lines} | {point.budget} | {over} | {point.reason} |")
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Report PAC refactor pressure point line counts.")
    parser.add_argument("root", nargs="?", default=".", help="repository root, default: current directory")
    parser.add_argument("--fail-over-budget", action="store_true", help="exit non-zero if any tracked file is over budget")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    print(render_markdown(root, PRESSURE_POINTS))

    if args.fail_over_budget:
        over_budget = [p for p in PRESSURE_POINTS if count_lines(root / p.path) > p.budget]
        return 1 if over_budget else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
