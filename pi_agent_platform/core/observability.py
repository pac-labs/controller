from __future__ import annotations

import logging
import logging.handlers
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .platform_home import pacp_path
from .observability_store import observability_store_status

_LOGGER_CONFIGURED = False
_LOG_DIR = pacp_path("logs")
_CONTROLLER_LOG = _LOG_DIR / "pac-controller.log"
_AUDIT_LOG = _LOG_DIR / "pac-audit.log"
_PI_AGENT_LOG = pacp_path("app") / "pi-agent-artifacts" / "pi-agent.log"
_PACCTL_LOG = pacp_path("app") / "pi-agent-artifacts" / "pacctl.log"
_CONTROLLER_WRAPPER_LOG = _LOG_DIR / "controller-pac-wrapper.log"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except Exception:
        return default


class AuditLogger:
    def __init__(self) -> None:
        self.logger = logging.getLogger("pac.audit")

    def info(self, event: str, **fields: Any) -> None:
        payload = " ".join(f"{key}={value!r}" for key, value in sorted(fields.items()))
        self.logger.info("%s %s", event, payload)


audit = AuditLogger()


def setup_pac_observability() -> dict[str, Any]:
    """Configure local, dependency-free PAC logging with rotation.

    PAC intentionally stays local-first.  The default monitoring base therefore
    uses Python's stdlib logging and rotating files under PACP_HOME/logs.  These
    files can be tailed from the UI/API and later shipped to Loki/OTel without
    making the controller depend on an external stack.
    """
    global _LOGGER_CONFIGURED
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    max_bytes = _int_env("PAC_LOG_MAX_BYTES", 10 * 1024 * 1024)
    backup_count = _int_env("PAC_LOG_BACKUP_COUNT", 7)
    level_name = os.environ.get("PAC_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    if not _LOGGER_CONFIGURED:
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
        root = logging.getLogger()
        root.setLevel(level)
        # Avoid duplicate handlers when tests import the app repeatedly.
        existing_paths = {getattr(handler, "baseFilename", None) for handler in root.handlers}
        if str(_CONTROLLER_LOG) not in existing_paths:
            handler = logging.handlers.RotatingFileHandler(
                _CONTROLLER_LOG,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            handler.setFormatter(formatter)
            handler.setLevel(level)
            root.addHandler(handler)
        audit_logger = logging.getLogger("pac.audit")
        audit_logger.setLevel(level)
        audit_logger.propagate = False
        audit_paths = {getattr(handler, "baseFilename", None) for handler in audit_logger.handlers}
        if str(_AUDIT_LOG) not in audit_paths:
            audit_handler = logging.handlers.RotatingFileHandler(
                _AUDIT_LOG,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            audit_handler.setFormatter(formatter)
            audit_handler.setLevel(level)
            audit_logger.addHandler(audit_handler)
        _LOGGER_CONFIGURED = True
        logging.getLogger("pac.observability").info(
            "PAC observability initialized log_dir=%s max_bytes=%s backup_count=%s level=%s",
            _LOG_DIR,
            max_bytes,
            backup_count,
            level_name,
        )
    return observability_status()


def _file_info(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        return {"path": str(path), "exists": True, "size_bytes": stat.st_size, "modified_at": modified}
    except FileNotFoundError:
        return {"path": str(path), "exists": False, "size_bytes": 0, "modified_at": None}


def log_file_map() -> dict[str, Path]:
    return {
        "controller": _CONTROLLER_LOG,
        "audit": _AUDIT_LOG,
        "wrapper": _CONTROLLER_WRAPPER_LOG,
        "pi-agent": _PI_AGENT_LOG,
        "pacctl": _PACCTL_LOG,
    }


def observability_status() -> dict[str, Any]:
    return {
        "logging": {
            "configured": _LOGGER_CONFIGURED,
            "backend": "python-stdlib-logging",
            "rotation": {
                "mode": "size",
                "max_bytes": _int_env("PAC_LOG_MAX_BYTES", 10 * 1024 * 1024),
                "backup_count": _int_env("PAC_LOG_BACKUP_COUNT", 7),
            },
            "level": os.environ.get("PAC_LOG_LEVEL", "INFO").upper(),
            "log_dir": str(_LOG_DIR),
            "files": {
                "controller": _file_info(_CONTROLLER_LOG),
                "audit": _file_info(_AUDIT_LOG),
                "wrapper": _file_info(_CONTROLLER_WRAPPER_LOG),
                "pi_agent": _file_info(_PI_AGENT_LOG),
                "pacctl": _file_info(_PACCTL_LOG),
            },
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pid": os.getpid(),
        },
        "store": observability_store_status(),
        "recommendation": "Use rotating files plus the embedded SQLite metrics/trace store for local diagnostics; export to Victoria/OpenTelemetry later only when configured.",
    }


def read_log_tail(path: Path, limit: int = 4000) -> dict[str, Any]:
    limit = max(1, min(int(limit or 4000), 200000))
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - limit), os.SEEK_SET)
            data = fh.read().decode("utf-8", errors="replace")
        if len(data) >= limit:
            data = data[data.find("\n") + 1 :] if "\n" in data else data
        return {"path": str(path), "content": data, "bytes": len(data.encode("utf-8", errors="replace"))}
    except FileNotFoundError:
        return {"path": str(path), "content": "", "bytes": 0}


def tail_log(name: str = "controller", limit: int = 4000) -> dict[str, Any]:
    path = log_file_map().get(name, _CONTROLLER_LOG)
    result = read_log_tail(path, limit=limit)
    result["name"] = name
    return result
