"""PTY shell sessions — interactive terminal for the agent."""
from __future__ import annotations
import os
import select
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Any

import pty
import struct
import termios

PTY_SESSIONS: dict[str, dict] = {}


@dataclass
class PtySession:
    id: str
    pid: int
    fd: int
    master_fd: int
    started_at: float
    command: str
    cwd: str
    status: str = "running"  # running | exited
    returncode: int | None = None
    rows: int = 24
    cols: int = 80


def open_pty_session(session_id: str, command: str, cwd: str | None = None, rows: int = 24, cols: int = 80) -> PtySession:
    """Open a new PTY session with the given command."""
    pid, master_fd = pty.fork()
    if pid == 0:
        # Child process
        if cwd:
            os.chdir(cwd)
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        # Run the command via shell
        subprocess.run(["/bin/sh", "-c", command], env=env)
        os._exit(0)
    else:
        # Parent process
        session = PtySession(
            id=session_id,
            pid=pid,
            fd=-1,
            master_fd=master_fd,
            started_at=time.time(),
            command=command,
            cwd=cwd or "/tmp",
            rows=rows,
            cols=cols,
        )
        PTY_SESSIONS[session_id] = session
        return session


def read_pty(session_id: str, max_bytes: int = 4096) -> str:
    """Read available output from a PTY session. Non-blocking."""
    session = PTY_SESSIONS.get(session_id)
    if not session:
        return ""
    try:
        if select.select([session.master_fd], [], [], 0)[0]:
            data = os.read(session.master_fd, max_bytes)
            return data.decode(errors="replace")
    except OSError:
        session.status = "exited"
    return ""


def write_pty(session_id: str, data: str) -> int:
    """Write keystrokes to a PTY session. Returns bytes written."""
    session = PTY_SESSIONS.get(session_id)
    if not session or session.status != "running":
        return 0
    try:
        return os.write(session.master_fd, data.encode())
    except OSError:
        session.status = "exited"
        return 0


def resize_pty(session_id: str, rows: int, cols: int) -> bool:
    """Resize a PTY session."""
    session = PTY_SESSIONS.get(session_id)
    if not session:
        return False
    session.rows = rows
    session.cols = cols
    try:
        # TIOCSWINSZ
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        termios.ioctl(session.master_fd, termios.TIOCSWINSZ, winsize)
        return True
    except Exception:
        return False


def close_pty_session(session_id: str) -> dict:
    """Close a PTY session gracefully."""
    session = PTY_SESSIONS.get(session_id)
    if not session:
        return {"id": session_id, "closed": False, "error": "not found"}
    try:
        os.close(session.master_fd)
    except OSError:
        pass
    try:
        os.kill(session.pid, signal.SIGTERM)
        time.sleep(0.2)
        os.kill(session.pid, signal.SIGKILL)
    except OSError:
        pass
    session.status = "exited"
    return {"id": session_id, "closed": True, "pid": session.pid}


def get_pty_session(session_id: str) -> PtySession | None:
    return PTY_SESSIONS.get(session_id)