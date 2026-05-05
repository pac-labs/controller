from __future__ import annotations

import os
from pathlib import Path


def pacp_home() -> Path:
    """Return the persistent PAC home directory.

    Defaults to ~/.pacp and can be overridden with PACP_HOME. This directory is
    the single source of truth for config, state, sessions, artifacts and locks,
    regardless of where the server binary/source is launched from.
    """
    return Path(os.environ.get("PACP_HOME", "~/.pacp")).expanduser().resolve()


def ensure_pacp_layout() -> Path:
    home = pacp_home()
    for name in ("config", "sessions", "workspaces", "artifacts", "logs", "cache", "run"):
        (home / name).mkdir(parents=True, exist_ok=True)
    return home


def pacp_path(*parts: str) -> Path:
    return ensure_pacp_layout().joinpath(*parts)
