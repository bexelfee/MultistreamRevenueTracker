"""Internal helpers shared by ws handler modules."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import WebSocket

LOGGER = logging.getLogger(__name__)

_PATH_WIN_RE = re.compile(r"[A-Za-z]:\\[^\s]+")
_PATH_UNIX_RE = re.compile(r"/[\w./-]+\.(?:py|json|txt|log|db)\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"\b(?:sk|pk)_(?:live|test)?_?[A-Za-z0-9]{8,}\b", re.IGNORECASE)


def user_facing_error_message(exc: BaseException) -> str:
    """Strip paths/tokens from exceptions before sending to dashboard alerts."""
    message = str(exc).strip() or exc.__class__.__name__
    message = _PATH_WIN_RE.sub("[path]", message)
    message = _PATH_UNIX_RE.sub("[file]", message)
    message = _TOKEN_RE.sub("[token]", message)
    if len(message) > 280:
        message = f"{message[:277]}\u2026"
    return message


async def send_error(websocket: WebSocket, exc: BaseException | str) -> None:
    """Send a scrubbed ``error`` envelope on the websocket."""
    text = exc if isinstance(exc, str) else user_facing_error_message(exc)
    await websocket.send_json({"type": "error", "message": text})


def require_dict(value: Any, field_name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value
