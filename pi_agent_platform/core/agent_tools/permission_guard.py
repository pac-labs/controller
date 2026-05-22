from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


_DEFAULT_DENIALS: dict[str, str] = {
    "file_read": "DENIED: file reads are denied",
    "file_write": "DENIED: file writes are denied",
    "shell": "DENIED: shell access is denied",
    "network": "DENIED: network access is denied",
    "git_push": "DENIED: git push access is denied",
    "cluster_write": "DENIED: cluster write access is denied",
    "secrets": "DENIED: secret access is denied",
    "dangerous": "DENIED: dangerous operations are denied",
}


@dataclass(frozen=True)
class PermissionGuard:
    """Small guard for repeated agent-tool permission checks.

    Tool handlers should ask this object for permission-class gates instead of
    reading PermissionRule fields inline.  The helper intentionally returns the
    standard PAC tool-result tuple so handlers can stay async/simple without a
    custom exception path.
    """

    rule: Any

    def level(self, permission_class: str) -> str:
        return str(getattr(self.rule, permission_class, "deny") or "deny")

    def require(self, permission_class: str, denied_message: str | None = None) -> tuple[str, bool] | None:
        if self.level(permission_class) == "deny":
            return denied_message or _DEFAULT_DENIALS.get(permission_class, f"DENIED: {permission_class} access is denied"), False
        return None

    def require_any(self, permission_classes: Iterable[str], denied_message: str) -> tuple[str, bool] | None:
        """Require at least one permission class to be non-denied."""
        if all(self.level(permission_class) == "deny" for permission_class in permission_classes):
            return denied_message, False
        return None
