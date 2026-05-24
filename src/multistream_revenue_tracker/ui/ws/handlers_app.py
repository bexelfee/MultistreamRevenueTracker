"""ping, app.shutdown, app.restart."""

from __future__ import annotations

from typing import Any

from .context import WsContext
from .registry import ws_handler


@ws_handler("ping")
async def handle_ping(ctx: WsContext, _message: dict[str, Any]) -> None:
    await ctx.websocket.send_json({"type": "pong"})


@ws_handler("app.shutdown.request")
async def handle_shutdown(ctx: WsContext, _message: dict[str, Any]) -> None:
    stop_requested = getattr(ctx.app.state, "stop_requested", None)
    if stop_requested is None:
        raise ValueError("shutdown is not available")
    ui_context = getattr(ctx.app.state, "ui_context", None)
    if ui_context is not None:
        ui_context.restart_requested = False
    stop_requested.set()
    await ctx.websocket.send_json({"type": "app.shutting_down"})


@ws_handler("app.restart.request")
async def handle_restart(ctx: WsContext, _message: dict[str, Any]) -> None:
    stop_requested = getattr(ctx.app.state, "stop_requested", None)
    if stop_requested is None:
        raise ValueError("shutdown is not available")
    ui_context = getattr(ctx.app.state, "ui_context", None)
    if ui_context is None:
        raise ValueError("restart is not available")
    ui_context.restart_requested = True
    stop_requested.set()
    await ctx.websocket.send_json({"type": "app.restarting"})
