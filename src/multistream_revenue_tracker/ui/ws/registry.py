"""Registry of WebSocket message handlers keyed by message ``type``."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .context import WsContext

LOGGER = logging.getLogger(__name__)

WsHandler = Callable[[WsContext, dict[str, Any]], Awaitable[None]]

_HANDLERS: dict[str, WsHandler] = {}


def ws_handler(*message_types: str) -> Callable[[WsHandler], WsHandler]:
    """Decorator: register the handler under one or more message-``type`` strings.

    Using a registry instead of a 600-line ``if/elif`` chain means each
    domain owns its handlers, adding a message-type stays localised, and
    tests can introspect ``registered_message_types()``.
    """
    if not message_types:
        raise ValueError("ws_handler() requires at least one message type")

    def decorator(handler: WsHandler) -> WsHandler:
        for msg_type in message_types:
            if msg_type in _HANDLERS:
                raise RuntimeError(f"duplicate ws handler registration: {msg_type!r}")
            _HANDLERS[msg_type] = handler
        return handler

    return decorator


async def dispatch(ctx: WsContext, message: dict[str, Any]) -> bool:
    """Invoke the registered handler for ``message['type']``.

    Returns True when a handler ran (even if it errored internally),
    False when no handler is registered for the given type.
    """
    msg_type = message.get("type")
    if not isinstance(msg_type, str):
        return False
    handler = _HANDLERS.get(msg_type)
    if handler is None:
        return False
    await handler(ctx, message)
    return True


def registered_message_types() -> list[str]:
    return sorted(_HANDLERS.keys())
