"""
Secrets store backed by LevelDB (plyvel) with Fernet encryption at rest.

Key layout:
  secret:<id>          → encrypted JSON: {"value": "<fernet-ciphertext>", "created_at": "...", "created_by": "...", "meta": {}}
  audit:<ts>:<uuid>    → access log entry (append-only)
  index:by-name:<name> → secondary: maps secret name → secret:<id>

Encryption: Fernet (AES-128-CBC + HMAC-SHA256). Key is derived from a master key file.
If no master key exists, one is generated and stored. Key rotation is a future concern.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import plyvel

# We'll import this after confirming it's available — handled lazily at module level
_fernet = None

SECRET_PREFIX = 'secret:'
AUDIT_PREFIX = 'audit:'
INDEX_PREFIX = 'index:by-name:'
_DB_PATH = None


def _load_fernet():
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        import base64

        key_file = _db_dir() / '.secret_key'
        if key_file.exists():
            raw = key_file.read_bytes()
        else:
            # Generate a new key
            raw = os.urandom(32)
            key_file.write_bytes(raw)
            key_file.chmod(0o600)

        # Derive a proper Fernet key from the raw bytes
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b'pac-secrets-v1', iterations=480000)
        key = kdf.derive(raw)
        fkey = base64.urlsafe_b64encode(key)
        _fernet = Fernet(fkey)
    return _fernet


def _db_dir():
    global _DB_PATH
    if _DB_PATH is None:
        from pi_agent_platform.core.platform_home import pacp_path
        _DB_PATH = pacp_path('secrets')
        _DB_PATH.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


class SecretStore:
    _instance: Optional['SecretStore'] = None

    def __init__(self, db_path: Optional[Path] = None):
        self._db = plyvel.DB(str(db_path or _db_dir()), create_if_missing=True)

    @classmethod
    def get_instance(cls) -> 'SecretStore':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def close(self):
        if self._instance is not None:
            self._instance._db.close()
            SecretStore._instance = None

    # ------------------------------------------------------------------
    # Encryption helpers
    # ------------------------------------------------------------------
    def _encrypt(self, plaintext: str) -> bytes:
        return _load_fernet().encrypt(plaintext.encode())

    def _decrypt(self, ciphertext: bytes) -> str:
        return _load_fernet().decrypt(ciphertext).decode()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def list(self) -> list[dict]:
        """Return metadata for all secrets (no values)."""
        results = []
        for key, val in self._db.iterator(prefix=SECRET_PREFIX.encode()):
            skey = key.decode()[len(SECRET_PREFIX):]
            try:
                data = json.loads(val.decode())
                results.append({
                    'id': skey,
                    'created_at': data.get('created_at'),
                    'created_by': data.get('created_by'),
                    'meta': data.get('meta', {}),
                    'has_value': bool(data.get('value')),
                })
            except Exception:
                results.append({'id': skey, 'error': 'corrupt'})
        return sorted(results, key=lambda r: r.get('created_at', ''))

    def get(self, secret_id: str) -> Optional[str]:
        """Return decrypted value, or None if not found."""
        key = f'{SECRET_PREFIX}{secret_id}'.encode()
        raw = self._db.get(key)
        if raw is None:
            return None
        try:
            data = json.loads(raw.decode())
            return self._decrypt(data['value'])
        except Exception:
            return None

    def set(self, secret_id: str, value: str, created_by: str = 'system', meta: Optional[dict] = None) -> dict:
        """Store a secret. Overwrites existing."""
        key = f'{SECRET_PREFIX}{secret_id}'.encode()
        now = datetime.now(timezone.utc).isoformat()
        # Store the encrypted value in the JSON
        payload = {
            'value': self._encrypt(value).decode(),
            'created_at': now,
            'created_by': created_by,
            'meta': meta or {},
        }
        self._db.put(key, json.dumps(payload).encode())

        # Secondary index by name
        idx_key = f'{INDEX_PREFIX}{secret_id}'.encode()
        self._db.put(idx_key, key)

        return {'id': secret_id, 'created_at': now, 'created_by': created_by, 'meta': meta or {}}

    def delete(self, secret_id: str) -> bool:
        key = f'{SECRET_PREFIX}{secret_id}'.encode()
        existing = self._db.get(key)
        if existing is None:
            return False
        self._db.delete(key)
        idx_key = f'{INDEX_PREFIX}{secret_id}'.encode()
        self._db.delete(idx_key)
        return True

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------
    def log_access(self, secret_id: str, endpoint_id: str, result: str):
        ts = datetime.now(timezone.utc).isoformat()
        entry = {
            'secret_id': secret_id,
            'endpoint_id': endpoint_id or 'controller',
            'result': result,  # 'ok' | 'denied' | 'not_found'
            'accessed_at': ts,
        }
        audit_key = f'{AUDIT_PREFIX}{ts}:{uuid.uuid4().hex[:8]}'.encode()
        self._db.put(audit_key, json.dumps(entry).encode())

    def audit_tail(self, limit: int = 20) -> list[dict]:
        results = []
        for key, val in self._db.iterator(reverse=True):
            k = key.decode()
            if not k.startswith(AUDIT_PREFIX):
                continue
            try:
                results.append(json.loads(val.decode()))
            except Exception:
                pass
            if len(results) >= limit:
                break
        return results
