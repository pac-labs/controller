from __future__ import annotations

from typing import Any

_CONTROLLER_STORE: Any | None = None


def set_controller_store(store: Any) -> None:
    global _CONTROLLER_STORE
    _CONTROLLER_STORE = store


def get_controller_store() -> Any | None:
    return _CONTROLLER_STORE
