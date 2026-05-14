from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import threading
from pathlib import Path
from typing import Any

from .platform_home import pacp_path

_VARIABLE_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


class SourceVariableStore:
    def __init__(self) -> None:
        self._path = pacp_path("config", "source-variables.json")
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"variables": {}}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {"variables": {}}
        if not isinstance(data, dict):
            return {"variables": {}}
        data.setdefault("variables", {})
        return data

    def _save(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def validate_id(self, variable_id: str) -> str:
        key = str(variable_id or "").strip()
        if not _VARIABLE_ID.match(key):
            raise ValueError("Variable name must start with a letter or underscore and may contain letters, digits, dots, dashes, and underscores")
        return key

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            payload = self._load()
            items = []
            for variable_id, item in sorted((payload.get("variables") or {}).items()):
                if not isinstance(item, dict):
                    continue
                items.append(
                    {
                        "id": variable_id,
                        "value": str(item.get("value") or ""),
                        "description": str(item.get("description") or ""),
                        "tags": [str(tag) for tag in (item.get("tags") or [])],
                        "updated_at": str(item.get("updated_at") or ""),
                        "created_at": str(item.get("created_at") or ""),
                    }
                )
            return items

    def get(self, variable_id: str) -> dict[str, Any] | None:
        key = self.validate_id(variable_id)
        with self._lock:
            item = (self._load().get("variables") or {}).get(key)
            if not isinstance(item, dict):
                return None
            return {
                "id": key,
                "value": str(item.get("value") or ""),
                "description": str(item.get("description") or ""),
                "tags": [str(tag) for tag in (item.get("tags") or [])],
                "updated_at": str(item.get("updated_at") or ""),
                "created_at": str(item.get("created_at") or ""),
            }

    def set(self, variable_id: str, value: str, description: str = "", tags: list[str] | None = None) -> dict[str, Any]:
        key = self.validate_id(variable_id)
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        clean_tags = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]
        with self._lock:
            payload = self._load()
            variables = payload.setdefault("variables", {})
            existing = variables.get(key) if isinstance(variables.get(key), dict) else {}
            variables[key] = {
                "value": str(value or ""),
                "description": str(description or ""),
                "tags": clean_tags,
                "created_at": existing.get("created_at") or now,
                "updated_at": now,
            }
            self._save(payload)
        return self.get(key) or {"id": key, "value": value, "description": description, "tags": clean_tags, "created_at": now, "updated_at": now}

    def delete(self, variable_id: str) -> bool:
        key = self.validate_id(variable_id)
        with self._lock:
            payload = self._load()
            variables = payload.setdefault("variables", {})
            if key not in variables:
                return False
            del variables[key]
            self._save(payload)
            return True


source_variable_store = SourceVariableStore()
