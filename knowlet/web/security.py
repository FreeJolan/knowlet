"""Request guards for the unauthenticated local web server.

The server has no auth: anything that can reach the port can call it. The
two realistic attackers are web pages open in the user's own browser:

* **Cross-site requests.** A page on ``https://evil.example`` can POST a
  form / ``fetch(..., {mode: "no-cors"})`` to ``http://127.0.0.1:<port>``.
  It cannot read the response, but the write already happened. Browsers
  always attach an ``Origin`` header to such requests, so unsafe methods
  carrying a foreign ``Origin`` are refused.
* **DNS rebinding.** ``evil.example`` re-resolves to ``127.0.0.1`` so the
  page becomes same-origin with the server and can read responses. The
  ``Host`` header still says ``evil.example``, so only loopback names, the
  address the connection actually arrived on, and explicitly configured
  names are accepted.

Requests without an ``Origin`` header (CLI, curl, scripts, the e2e fixture)
are not browser cross-site requests and pass through.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from typing import Any
from urllib.parse import urlsplit

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})
# Origins the Tauri webview may use for its bundled (non-navigated) pages.
TAURI_ORIGINS = frozenset(
    {"tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"}
)
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ALLOWED_HOSTS_ENV = "KNOWLET_ALLOWED_HOSTS"


def _hostname_of_host_header(value: str) -> str | None:
    """``127.0.0.1:8765`` → ``127.0.0.1``; ``[::1]:8765`` → ``::1``."""
    value = value.strip()
    if not value:
        return None
    try:
        parsed = urlsplit(f"//{value}")
        hostname = parsed.hostname
        _ = parsed.port  # raises ValueError on a malformed port
    except ValueError:
        return None
    return hostname.lower() if hostname else None


def configured_extra_hosts() -> frozenset[str]:
    raw = os.environ.get(ALLOWED_HOSTS_ENV, "")
    return frozenset(h.strip().lower() for h in raw.split(",") if h.strip())


def host_allowed(host_header: str, *, server_host: str | None, extra_hosts: Iterable[str]) -> bool:
    hostname = _hostname_of_host_header(host_header)
    if hostname is None:
        return False
    if hostname in LOOPBACK_HOSTNAMES or hostname in extra_hosts:
        return True
    # A request addressed to the literal interface address it arrived on
    # (e.g. ``--host 0.0.0.0`` reached via the LAN IP) is not a rebinding
    # attack: rebinding needs an attacker-controlled *name* in Host.
    return server_host is not None and hostname == server_host.lower()


def origin_allowed(origin: str, *, host_header: str | None) -> bool:
    origin = origin.strip().lower()
    if origin in TAURI_ORIGINS:
        return True
    try:
        parsed = urlsplit(origin)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not hostname:
        return False
    if hostname in LOOPBACK_HOSTNAMES:
        return True
    # Same-origin: the page was served by this server under the same
    # (already Host-validated) authority.
    return host_header is not None and parsed.netloc == host_header.strip().lower()


class LocalRequestGuard:
    """Pure ASGI middleware (not ``BaseHTTPMiddleware``) so SSE streams
    pass through untouched."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        extra_hosts: Iterable[str] | None = None,
        max_body_bytes: Callable[[], int] | None = None,
    ) -> None:
        self.app = app
        self.extra_hosts = frozenset(
            h.lower() for h in (configured_extra_hosts() if extra_hosts is None else extra_hosts)
        )
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers: dict[str, str] = {}
        for raw_key, raw_value in scope.get("headers") or []:
            headers.setdefault(raw_key.decode("latin-1").lower(), raw_value.decode("latin-1"))

        host = headers.get("host")
        server = scope.get("server")
        server_host = str(server[0]) if server else None
        if host is not None and not host_allowed(
            host, server_host=server_host, extra_hosts=self.extra_hosts
        ):
            await _reject(scope, send, "host not allowed")
            return

        method = scope.get("method", "GET").upper()
        is_unsafe = scope["type"] == "websocket" or method in UNSAFE_METHODS
        origin = headers.get("origin")
        if is_unsafe and origin is not None and not origin_allowed(origin, host_header=host):
            await _reject(scope, send, "cross-origin request refused")
            return

        # Starlette spools a whole multipart body to disk before any
        # endpoint-level size check can run; refuse declared giants early.
        if self.max_body_bytes is not None and scope["type"] == "http":
            declared = headers.get("content-length", "").strip()
            if declared.isdigit() and int(declared) > self.max_body_bytes():
                await _reject(scope, send, "request body too large", status=413)
                return

        await self.app(scope, receive, send)


async def _reject(scope: Scope, send: Send, detail: str, *, status: int = 403) -> None:
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
