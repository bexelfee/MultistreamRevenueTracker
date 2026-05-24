"""Per-message handler context passed to each ``@ws_handler``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket

if TYPE_CHECKING:
    from ...goals.goal_service import GoalService
    from ..goal_broadcast import GoalBroadcaster


@dataclass
class WsContext:
    """Plumbing every handler needs.

    Carrying these on a dataclass avoids each handler restating four
    arguments and lets us add new shared state (e.g. tracing) in one place.
    """

    websocket: WebSocket
    goal_service: "GoalService | None"
    broadcaster: "GoalBroadcaster"
    app: Any
