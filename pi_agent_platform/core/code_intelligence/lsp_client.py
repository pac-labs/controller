from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import pathname2url

from .scanner import CODE_EXTENSIONS


@dataclass(frozen=True, slots=True)
class ServerSpec:
    language: str
    binaries: tuple[tuple[str, ...], ...]
    extensions: tuple[str, ...]


SERVER_SPECS: dict[str, ServerSpec] = {
    "rust": ServerSpec("rust", (("rust-analyzer",),), (".rs",)),
    "python": ServerSpec("python", (("pyright-langserver", "--stdio"), ("pylsp",)), (".py",)),
    "go": ServerSpec("go", (("gopls",),), (".go",)),
    "typescript": ServerSpec(
        "typescript",
        (("typescript-language-server", "--stdio"),),
        (".ts", ".tsx", ".js", ".jsx"),
    ),
    "csharp": ServerSpec("csharp", (("csharp-ls",),), (".cs",)),
}


def file_uri(path: Path) -> str:
    return "file://" + pathname2url(str(path.resolve()))


def uri_path(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return uri
    return unquote(parsed.path)


def detect_language_for_file(path: Path, explicit: str | None = None) -> str | None:
    if explicit and explicit != "auto":
        return explicit
    return CODE_EXTENSIONS.get(path.suffix.lower())


def preferred_command(language: str) -> tuple[str, ...] | None:
    spec = SERVER_SPECS.get(language)
    if not spec:
        return None
    for command in spec.binaries:
        if shutil.which(command[0]):
            return command
    return None


class LspError(RuntimeError):
    pass


class LspClient:
    def __init__(self, root: Path, language: str, command: tuple[str, ...]) -> None:
        self.root = root.resolve()
        self.language = language
        self.command = command
        self.started_at = time.time()
        self._next_id = 1
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._opened: set[str] = set()
        self._lock = threading.Lock()
        self._closed = False
        self._proc = subprocess.Popen(
            list(command),
            cwd=str(self.root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=0,
        )
        self._reader = threading.Thread(target=self._read_loop, name=f"pac-lsp-{language}", daemon=True)
        self._reader.start()
        self.initialize()

    @property
    def pid(self) -> int | None:
        return self._proc.pid

    def initialize(self) -> None:
        result = self.request(
            "initialize",
            {
                "processId": None,
                "rootUri": file_uri(self.root),
                "workspaceFolders": [{"uri": file_uri(self.root), "name": self.root.name}],
                "capabilities": {
                    "textDocument": {
                        "definition": {"dynamicRegistration": False},
                        "references": {"dynamicRegistration": False},
                        "documentSymbol": {"dynamicRegistration": False, "hierarchicalDocumentSymbolSupport": True},
                        "hover": {"dynamicRegistration": False},
                        "callHierarchy": {"dynamicRegistration": False},
                        "typeHierarchy": {"dynamicRegistration": False},
                        "rename": {"dynamicRegistration": False, "prepareSupport": True},
                    },
                    "workspace": {"workspaceFolders": True},
                },
            },
            timeout=15,
        )
        self.notify("initialized", {})
        if not isinstance(result, dict):
            return

    def alive(self) -> bool:
        return not self._closed and self._proc.poll() is None

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 10) -> Any:
        if self._closed or self._proc.poll() is not None:
            raise LspError(f"language server for {self.language} is not running")
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            responses: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = responses
            self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        try:
            message = responses.get(timeout=timeout)
        except queue.Empty as exc:
            self._pending.pop(request_id, None)
            raise LspError(f"{method} timed out after {timeout:.0f}s") from exc
        if "error" in message:
            raise LspError(json.dumps(message["error"], ensure_ascii=False))
        return message.get("result")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if self._closed or self._proc.poll() is not None:
            return
        with self._lock:
            self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def open_document(self, path: Path) -> str:
        real = path.resolve()
        if self.root != real and self.root not in real.parents:
            raise LspError("document path escapes workspace")
        uri = file_uri(real)
        if uri in self._opened:
            return uri
        text = real.read_text(errors="replace")
        self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": _language_id(self.language),
                    "version": 1,
                    "text": text,
                }
            },
        )
        self._opened.add(uri)
        return uri

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._proc.poll() is None:
                try:
                    self.request("shutdown", {}, timeout=3)
                except Exception:
                    pass
                try:
                    self.notify("exit", {})
                except Exception:
                    pass
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
        finally:
            for q in self._pending.values():
                q.put_nowait({"error": {"message": "language server stopped"}})
            self._pending.clear()

    def _write(self, payload: dict[str, Any]) -> None:
        if not self._proc.stdin:
            raise LspError("language server stdin is closed")
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii")
        self._proc.stdin.write(header + raw)
        self._proc.stdin.flush()

    def _read_loop(self) -> None:
        stream = self._proc.stdout
        if not stream:
            return
        while not self._closed:
            try:
                headers: dict[str, str] = {}
                while True:
                    line = stream.readline()
                    if not line:
                        return
                    if line in {b"\r\n", b"\n"}:
                        break
                    decoded = line.decode("ascii", errors="replace").strip()
                    if ":" in decoded:
                        key, value = decoded.split(":", 1)
                        headers[key.lower()] = value.strip()
                length = int(headers.get("content-length") or "0")
                if length <= 0:
                    continue
                body = stream.read(length)
                message = json.loads(body.decode("utf-8", errors="replace"))
            except Exception:
                continue
            request_id = message.get("id")
            if isinstance(request_id, int) and request_id in self._pending:
                self._pending.pop(request_id).put(message)


_CLIENTS: dict[tuple[str, str], LspClient] = {}
_CLIENTS_LOCK = threading.Lock()


def client_for(root: Path, language: str) -> LspClient:
    command = preferred_command(language)
    if not command:
        raise LspError(f"no language server available for {language}")
    key = (str(root.resolve()), language)
    with _CLIENTS_LOCK:
        client = _CLIENTS.get(key)
        if client and client.alive():
            return client
        if client:
            client.shutdown()
        client = LspClient(root.resolve(), language, command)
        _CLIENTS[key] = client
        return client


def active_clients() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with _CLIENTS_LOCK:
        for (root, language), client in list(_CLIENTS.items()):
            if not client.alive():
                _CLIENTS.pop((root, language), None)
                continue
            rows.append({
                "root": root,
                "language": language,
                "pid": client.pid,
                "command": list(client.command),
                "opened_documents": len(client._opened),
                "uptime_seconds": round(time.time() - client.started_at, 3),
            })
    return rows


def shutdown_clients(root: Path | None = None, language: str | None = None) -> int:
    stopped = 0
    with _CLIENTS_LOCK:
        for key, client in list(_CLIENTS.items()):
            key_root, key_language = key
            if root and str(root.resolve()) != key_root:
                continue
            if language and language != key_language:
                continue
            client.shutdown()
            _CLIENTS.pop(key, None)
            stopped += 1
    return stopped


def _language_id(language: str) -> str:
    return {"typescript": "typescript", "csharp": "csharp"}.get(language, language)
