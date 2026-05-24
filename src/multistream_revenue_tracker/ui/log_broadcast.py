from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from collections.abc import Callable

from ..log_scrubbing import attach_scrubber_to_handler
from ..session_logging import LOG_FORMAT

HISTORY_MAX = 500

_history: deque[str] = deque(maxlen=HISTORY_MAX)
_subscribers: list[asyncio.Queue[str]] = []
_lock = threading.Lock()
_handler: logging.Handler | None = None


class LogBroadcastHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            self.handleError(record)
            return
        line = line.replace("\n", " ").replace("\r", "")
        with _lock:
            _history.append(line)
            subscribers = list(_subscribers)
        for queue in subscribers:
            try:
                queue.put_nowait(line)
            except asyncio.QueueFull:
                pass


def register_log_broadcast_handler() -> None:
    global _handler
    if _handler is not None:
        return
    _handler = LogBroadcastHandler()
    _handler.setFormatter(logging.Formatter(LOG_FORMAT))
    attach_scrubber_to_handler(_handler)
    logging.getLogger().addHandler(_handler)


def subscribe() -> tuple[list[str], asyncio.Queue[str], Callable[[], None]]:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=200)
    with _lock:
        history = list(_history)
        _subscribers.append(queue)

    def unsubscribe() -> None:
        with _lock:
            if queue in _subscribers:
                _subscribers.remove(queue)

    return history, queue, unsubscribe
