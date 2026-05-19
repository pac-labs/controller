"""Minimal HTTP server for Let's Encrypt ACME HTTP-01 challenge."""
from __future__ import annotations

import asyncio
import re
from typing import Callable

_challenge_tokens: dict[str, str] = {}  # token -> key authorization
_acme_server: asyncio.Server | None = None


async def start_acme_server(port: int, on_request: Callable[[str, str], None] | None = None) -> asyncio.Server:
    """Start a minimal HTTP server on port 80 to serve ACME HTTP-01 challenges."""
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                await writer.wait_closed()
                return
            method, path, _ = request_line.decode().split(' ', 2)
            if method != 'GET':
                writer.close()
                await writer.wait_closed()
                return
            # Consume headers
            while True:
                line = await reader.readline()
                if line == b'\r\n' or line == b'\n' or not line:
                    break
            path = path.strip()
            # Match /.well-known/acme-challenge/<token>
            match = re.match(r'^/\.well-known/acme-challenge/([A-Za-z0-9_-]+)$', path)
            if match:
                token = match.group(1)
                key_auth = _challenge_tokens.get(token, '')
                if key_auth:
                    body = f"{key_auth}".encode()
                    writer.write(b"HTTP/1.1 200 OK\r\n")
                    writer.write(b"Content-Type: text/plain\r\n")
                    writer.write(f"Content-Length: {len(body)}\r\n".encode())
                    writer.write(b"Connection: close\r\n")
                    writer.write(b"\r\n")
                    writer.write(body)
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                    if on_request:
                        on_request(token, key_auth)
                    return
            # ACME TLS-ALPN-01 or other path — 404
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except Exception:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(handler, "0.0.0.0", port)
    return server


async def stop_acme_server() -> None:
    global _acme_server
    if _acme_server:
        _acme_server.close()
        _acme_server = None


def set_challenge_token(token: str, key_auth: str) -> None:
    _challenge_tokens[token] = key_auth


def clear_challenge_tokens() -> None:
    _challenge_tokens.clear()