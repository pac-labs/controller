from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from .models import DirectoryCredential, now_utc

_TOKEN_PREFIX = "pac_"


def generate_token_secret() -> str:
    """Return a new opaque PAC API token. The raw value is shown once."""
    return _TOKEN_PREFIX + secrets.token_urlsafe(48)


def hash_token_secret(token: str) -> str:
    """Hash a token with SHA-256 for lookup without storing the raw secret."""
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def normalize_certificate_fingerprint(value: str) -> str:
    text = str(value or "").strip().lower().replace(" ", "")
    if not text:
        return ""
    if text.startswith("sha256:"):
        return text
    if text.startswith("sha256="):
        return "sha256:" + text.split("=", 1)[1]
    if len(text) == 64 and all(ch in "0123456789abcdef" for ch in text):
        return "sha256:" + text
    return text


def certificate_fingerprint(certificate_pem_or_der: str) -> str:
    """Create a stable fingerprint for PEM/DER text submitted through the API."""
    text = str(certificate_pem_or_der or "").strip()
    if not text:
        raise ValueError("certificate_pem or fingerprint required")
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def public_credential(credential: DirectoryCredential) -> dict[str, Any]:
    """Return credential metadata safe for API responses."""
    return {
        "id": credential.id,
        "principal_id": credential.principal_id,
        "kind": credential.kind,
        "name": credential.name,
        "status": credential.status,
        "fingerprint": credential.fingerprint,
        "created_at": credential.created_at.isoformat(),
        "expires_at": credential.expires_at.isoformat() if credential.expires_at else None,
        "last_used_at": credential.last_used_at.isoformat() if credential.last_used_at else None,
        "metadata": credential.metadata or {},
    }


def credential_expired(credential: DirectoryCredential, *, at: datetime | None = None) -> bool:
    if credential.status != "active":
        return True
    if not credential.expires_at:
        return False
    check_at = at or now_utc()
    expires_at = credential.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= check_at


def new_token_credential(
    principal_id: str,
    *,
    name: str | None = None,
    ttl_hours: int | None = None,
    kind: str = "api_token",
    metadata: dict[str, Any] | None = None,
) -> tuple[DirectoryCredential, str]:
    raw_token = generate_token_secret()
    expires_at = None
    if ttl_hours:
        expires_at = now_utc() + timedelta(hours=max(1, int(ttl_hours)))
    credential = DirectoryCredential(
        principal_id=principal_id,
        kind=kind,  # type: ignore[arg-type]
        name=name or "API token",
        secret_hash=hash_token_secret(raw_token),
        fingerprint=None,
        expires_at=expires_at,
        metadata=metadata or {},
    )
    return credential, raw_token


def new_certificate_credential(
    principal_id: str,
    *,
    name: str | None = None,
    certificate_pem: str | None = None,
    fingerprint: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DirectoryCredential:
    normalized_fingerprint = normalize_certificate_fingerprint(str(fingerprint or ""))
    if not normalized_fingerprint:
        normalized_fingerprint = certificate_fingerprint(certificate_pem or "")
    credential = DirectoryCredential(
        principal_id=principal_id,
        kind="certificate",
        name=name or "Certificate",
        secret_hash=None,
        fingerprint=normalized_fingerprint,
        metadata=metadata or {},
    )
    return credential


def token_kind_for_principal(principal_kind: str) -> str:
    if principal_kind == "endpoint":
        return "endpoint_token"
    if principal_kind == "provider":
        return "provider_token"
    return "api_token"
