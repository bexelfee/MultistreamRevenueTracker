"""WebSocket handler registry for the dashboard's /ws endpoint.

Each handler module registers callable(s) under a message ``type`` string;
``routes.ui_websocket`` dispatches incoming messages through ``dispatch``.

Importing this package triggers registration in every submodule.
"""

from __future__ import annotations

from .context import WsContext
from .registry import dispatch, ws_handler, registered_message_types

# Importing handler modules registers their @ws_handler functions.
from . import (  # noqa: F401  (side-effect imports)
    handlers_app,
    handlers_appearance,
    handlers_config,
    handlers_goals,
    handlers_monitors,
    handlers_revenue,
    handlers_subathon,
    handlers_test,
)

__all__ = ["WsContext", "dispatch", "ws_handler", "registered_message_types"]
