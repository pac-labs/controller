from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    _CRYPTO_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - dependency presence varies per install
    Fernet = None  # type: ignore[assignment]
    hashes = None  # type: ignore[assignment]
    PBKDF2HMAC = None  # type: ignore[assignment]
    _CRYPTO_IMPORT_ERROR = exc

from .platform_home import pacp_path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SecretStore:
    def __init__(self) -> None:
        self._dir = pacp_path("config", "secrets")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._data_file = self._dir / "store.json"
        self._audit_file = self._dir / "audit.jsonl"
        self._key_file = self._dir / ".master_key"
        self._lock = Lock()
        self._fernet = None

    def _ensure_crypto_available(self) -> None:
        if _CRYPTO_IMPORT_ERROR is not None:
            raise RuntimeError("The cryptography package is required for PAC secrets support") from _CRYPTO_IMPORT_ERROR

    def _require_crypto(self) -> None:
        self._ensure_crypto_available()
        if self._fernet is None:
            assert Fernet is not None
            self._fernet = Fernet(self._derive_key())

    def _derive_key(self) -> bytes:
        self._ensure_crypto_available()
        if self._key_file.exists():
            raw = self._key_file.read_bytes()
        else:
            raw = os.urandom(32)
            self._key_file.write_bytes(raw)
            try:
                self._key_file.chmod(0o600)
            except Exception:
                pass
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"pac-secrets-v1",
            iterations=480000,
        )
        return base64.urlsafe_b64encode(kdf.derive(raw))

    def _read(self) -> dict[str, Any]:
        if not self._data_file.exists():
            return {"secrets": {}}
        return json.loads(self._data_file.read_text(encoding="utf-8"))

    def _write(self, payload: dict[str, Any]) -> None:
        self._data_file.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _audit(self, event: str, secret_id: str, actor: str, detail: dict[str, Any] | None = None) -> None:
        entry = {
            "event": event,
            "secret_id": secret_id,
            "actor": actor,
            "detail": detail or {},
            "created_at": _utc_now(),
        }
        with self._audit_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            payload = self._read()
        results = []
        for secret_id, item in payload.get("secrets", {}).items():
            results.append(
                {
                    "id": secret_id,
                    "created_at": item.get("created_at"),
                    "updated_at": item.get("updated_at"),
                    "created_by": item.get("created_by"),
                    "updated_by": item.get("updated_by"),
                    "meta": item.get("meta", {}),
                    "has_value": bool(item.get("ciphertext")),
                }
            )
        return sorted(results, key=lambda item: item.get("id", ""))

    def get(self, secret_id: str) -> str | None:
        with self._lock:
            payload = self._read()
            item = payload.get("secrets", {}).get(secret_id)
        if not item or not item.get("ciphertext"):
            return None
        self._require_crypto()
        assert self._fernet is not None
        return self._fernet.decrypt(item["ciphertext"].encode("utf-8")).decode("utf-8")

    def set(self, secret_id: str, value: str, actor: str = "system", meta: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_crypto()
        assert self._fernet is not None
        now = _utc_now()
        with self._lock:
            payload = self._read()
            secrets = payload.setdefault("secrets", {})
            previous = secrets.get(secret_id, {})
            secrets[secret_id] = {
                "ciphertext": self._fernet.encrypt(value.encode("utf-8")).decode("utf-8"),
                "created_at": previous.get("created_at") or now,
                "updated_at": now,
                "created_by": previous.get("created_by") or actor,
                "updated_by": actor,
                "meta": meta or previous.get("meta", {}),
            }
            self._write(payload)
        self._audit("set", secret_id, actor, {"meta": meta or {}})
        return {
            "id": secret_id,
            "created_at": secrets[secret_id]["created_at"],
            "updated_at": now,
            "created_by": secrets[secret_id]["created_by"],
            "updated_by": actor,
            "meta": secrets[secret_id]["meta"],
            "has_value": True,
        }

    def delete(self, secret_id: str, actor: str = "system") -> bool:
        with self._lock:
            payload = self._read()
            secrets = payload.get("secrets", {})
            if secret_id not in secrets:
                return False
            del secrets[secret_id]
            self._write(payload)
        self._audit("delete", secret_id, actor)
        return True

    def audit_tail(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self._audit_file.exists():
            return []
        rows = [json.loads(line) for line in self._audit_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        return rows[-limit:]


secret_store = SecretStore()
