"""Shared helpers for the localhost OAuth callback server used by Patreon and YouTube.

Both clients used to inline identical ``_force_close_oauth_server`` helpers
and copy/paste the rationale comment. This module owns that helper so the
""don't call server.shutdown()" warning lives in exactly one place.

We intentionally do NOT unify the full ``run_local_server`` loops yet —
the Google library uses ``wsgiref`` with a custom WSGI app while Patreon
uses the stdlib ``http.server`` with a ``BaseHTTPRequestHandler``. The two
flows differ enough that fitting them under one API would be more code
than the duplication saves.
"""

from __future__ import annotations

from typing import Any, Protocol


class _ClosableServer(Protocol):
    """Structural typing match for both ``HTTPServer`` and ``wsgiref.WSGIServer``."""

    def server_close(self) -> None: ...


def force_close_oauth_server(server: _ClosableServer | None) -> None:
    """Close the localhost OAuth callback server promptly.

    Important: we deliberately do **not** call ``server.shutdown()`` here.
    Both call sites drive the server via ``server.handle_request()`` inside a
    polling loop rather than ``serve_forever()``. ``shutdown()`` blocks until
    the internal ``__is_shut_down`` event is set, but that event is only set
    by ``serve_forever()``'s exit path. Calling it would hang the cancel/
    shutdown path indefinitely. Closing the socket is enough: the next
    ``handle_request()`` raises ``OSError`` and the loop exits.
    """
    if server is None:
        return
    sock: Any = getattr(server, "socket", None)
    if sock is not None:
        try:
            sock.close()
        except OSError:
            pass
    try:
        server.server_close()
    except OSError:
        pass
