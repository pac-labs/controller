from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .generated_file_housekeeping import CleanupPolicy, housekeeping_status, run_generated_file_housekeeping

_RUNNING = False
_LAST_RESULT: dict[str, Any] | None = None
_LOCK = threading.Lock()


def last_housekeeping_result() -> dict[str, Any] | None:
    with _LOCK:
        return dict(_LAST_RESULT) if isinstance(_LAST_RESULT, dict) else None


def run_housekeeping_once(
    *,
    app_root: Path,
    debug_bundle_root: Path,
    dry_run: bool = False,
    policy: CleanupPolicy | None = None,
) -> dict[str, Any]:
    global _LAST_RESULT
    result = run_generated_file_housekeeping(
        app_root=app_root,
        debug_bundle_root=debug_bundle_root,
        dry_run=dry_run,
        policy=policy,
    )
    result['started_at'] = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        _LAST_RESULT = result
    return result


def housekeeping_state(*, app_root: Path, debug_bundle_root: Path) -> dict[str, Any]:
    return {
        'ok': True,
        'running': _RUNNING,
        'last_result': last_housekeeping_result(),
        'status': housekeeping_status(app_root=app_root, debug_bundle_root=debug_bundle_root),
    }


def start_housekeeping_thread(
    *,
    app_root: Path,
    debug_bundle_root: Path,
    store: Any | None = None,
    reason: str = 'startup',
    policy: CleanupPolicy | None = None,
) -> bool:
    """Start a one-shot housekeeping run in the background.

    PAC uses this on startup and after updates. It is intentionally a one-shot
    service rather than a permanent loop so it cannot compete with active update
    extraction, package upload, or binary builds.
    """
    global _RUNNING
    with _LOCK:
        if _RUNNING:
            return False
        _RUNNING = True

    def worker() -> None:
        global _RUNNING
        try:
            if store is not None:
                try:
                    from .models import Event
                    store.add_event(Event(session_id='system', type='housekeeping_started', message=f'PAC generated-file housekeeping started ({reason}).', data={'reason': reason}))
                except Exception:
                    pass
            result = run_housekeeping_once(app_root=app_root, debug_bundle_root=debug_bundle_root, dry_run=False, policy=policy)
            if store is not None:
                try:
                    from .models import Event
                    store.add_event(Event(
                        session_id='system',
                        type='housekeeping_completed',
                        message=f"PAC housekeeping completed: {result.get('deleted_count', 0)} item(s), {result.get('deleted_bytes', 0)} byte(s) reclaimed.",
                        data={'reason': reason, 'result': result},
                    ))
                except Exception:
                    pass
        except Exception as exc:
            with _LOCK:
                global _LAST_RESULT
                _LAST_RESULT = {'ok': False, 'error': str(exc), 'reason': reason, 'generated_at': datetime.now(timezone.utc).isoformat()}
            if store is not None:
                try:
                    from .models import Event
                    store.add_event(Event(session_id='system', type='housekeeping_failed', message=f'PAC housekeeping failed: {exc}', data={'reason': reason, 'error': str(exc)}))
                except Exception:
                    pass
        finally:
            with _LOCK:
                _RUNNING = False

    threading.Thread(target=worker, daemon=True, name='pac-housekeeping').start()
    return True
