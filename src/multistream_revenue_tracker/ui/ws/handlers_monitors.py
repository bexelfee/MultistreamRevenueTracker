"""monitor.connect/disconnect/restart."""

from __future__ import annotations

from typing import Any

from ._helpers import send_error
from .context import WsContext
from .registry import ws_handler


def _coordinator_or_error(ctx: WsContext):
    coordinator = getattr(ctx.app.state, "monitor_coordinator", None)
    if coordinator is None:
        return None
    return coordinator


@ws_handler("monitor.connect.request", "monitor.disconnect.request")
async def handle_connect_or_disconnect(ctx: WsContext, message: dict[str, Any]) -> None:
    coordinator = _coordinator_or_error(ctx)
    if coordinator is None:
        await send_error(ctx.websocket, "monitors are not available")
        return
    monitor_id = str(message.get("monitor_id", "")).strip()
    if not monitor_id:
        await send_error(ctx.websocket, "monitor_id is required")
        return
    try:
        if message["type"] == "monitor.connect.request":
            coordinator.request_connect(monitor_id)
        else:
            coordinator.request_disconnect(monitor_id)
    except (TypeError, ValueError) as exc:
        await send_error(ctx.websocket, exc)


@ws_handler("monitor.restart.request")
async def handle_restart(ctx: WsContext, message: dict[str, Any]) -> None:
    coordinator = _coordinator_or_error(ctx)
    if coordinator is None:
        raise ValueError("monitor restart is not available")
    monitor_id = str(message.get("monitor_id", "")).strip()
    if not monitor_id:
        raise ValueError("monitor_id is required")
    coordinator.request_restart(monitor_id)
