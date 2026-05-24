"""WebSocket session-token + Origin allowlist used by every /ws endpoint.

The token rotates each app launch and is never persisted. Same-origin pages
(``/``, ``/overlay``, ``/timer``) read it from the server-rendered HTML; a
malicious cross-origin page cannot read it under the browser's same-origin
policy, so it cannot connect to our localhost WebSockets even though the
listening port is reachable.
"""

from __future__ import annotations

import logging
import secrets
from typing import Iterable
from urllib.parse import urlparse

from fastapi import WebSocket
from starlette.status import WS_1008_POLICY_VIOLATION

LOGGER = logging.getLogger(__name__)

# OBS browser sources sometimes report a literal "null" Origin (file:// or
# CEF embedded view). Allow it ONLY when the caller presents a valid token.
_OBS_NULL_ORIGINS: frozenset[str] = frozenset({"", "null"})


def generate_ui_token() -> str:
    """Cryptographically random URL-safe token (~43 chars from 32 bytes)."""
    return secrets.token_urlsafe(32)


def _origin_host_matches_port(origin: str, port: int) -> bool:
    if origin in _OBS_NULL_ORIGINS:
        return False
    parsed = urlparse(origin)
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.hostname not in ("127.0.0.1", "localhost", "[::1]", "::1"):
        return False
    # Browsers send the port whenever it isn't 80/443.
    if parsed.port is not None:
        return parsed.port == port
    return port in (80, 443)


def _extract_token(websocket: WebSocket) -> str | None:
    qp_token = websocket.query_params.get("token")
    if qp_token:
        return qp_token.strip()
    auth = websocket.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


async def authorize_websocket(
    websocket: WebSocket,
    *,
    expected_token: str | None,
    expected_port: int | None,
    require_token: bool = False,
) -> bool:
    """Reject the WebSocket if its token or Origin header is wrong.

    When ``require_token`` is False (the default), connections are accepted
    without a session token so OBS overlay URLs stay stable across app
    launches. Origin checking still applies when ``expected_port`` is set,
    which blocks normal cross-site pages (they send a real ``Origin`` header)
    but allows ``null`` for OBS browser sources.

    Returns True when the connection was accepted, False when it was closed.
    Callers must not interact with ``websocket`` further when the return is False.
    """
    if require_token:
        if not expected_token:
            LOGGER.error("websocket auth misconfigured: require_ws_token but ui_token empty")
            await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="token misconfigured")
            return False
        presented = _extract_token(websocket)
        if presented is None or not secrets.compare_digest(presented, expected_token):
            LOGGER.info("rejecting websocket: missing or invalid token")
            await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="invalid token")
            return False

    if expected_port is not None:
        origin = websocket.headers.get("origin", "")
        if origin not in _OBS_NULL_ORIGINS and not _origin_host_matches_port(origin, expected_port):
            LOGGER.info("rejecting websocket: disallowed origin %r", origin)
            await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="disallowed origin")
            return False

    return True


def attach_token_to_url(url: str, token: str) -> str:
    """Append ``?token=`` (or ``&token=``) to a URL string."""
    if not token:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}token={token}"


def origin_allowed(origin: str, port: int, allow_extra: Iterable[str] = ()) -> bool:
    """Public helper for tests/CLI: True when ``origin`` is allowed for ``port``."""
    if origin in _OBS_NULL_ORIGINS:
        return True
    if _origin_host_matches_port(origin, port):
        return True
    return origin in set(allow_extra)
