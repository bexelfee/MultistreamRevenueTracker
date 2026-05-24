"""test_event.inject, test_event.delete_all (only when enable_test_events)."""

from __future__ import annotations

import asyncio
from typing import Any

from ...test_events import build_test_stream_event, overrides_from_ui
from ._helpers import send_error
from .context import WsContext
from .registry import ws_handler


@ws_handler("test_event.inject")
async def handle_test_inject(ctx: WsContext, message: dict[str, Any]) -> None:
    if ctx.goal_service is None:
        await send_error(ctx.websocket, "goals are not configured")
        return
    try:
        if not ctx.app.state.allow_test_events:
            raise ValueError("test events are disabled in config (app.enable_test_events)")
        event_queue = ctx.app.state.event_queue
        if event_queue is None:
            raise ValueError("event queue is not available")
        event_type = str(message.get("event_type", "")).strip()
        raw_overrides = message.get("overrides")
        if raw_overrides is not None and not isinstance(raw_overrides, dict):
            raise ValueError("overrides must be an object")
        event = build_test_stream_event(event_type, overrides_from_ui(raw_overrides or {}))
        event_queue.put_nowait(event)
    except (TypeError, ValueError) as exc:
        await send_error(ctx.websocket, exc)


@ws_handler("test_event.delete_all")
async def handle_test_delete_all(ctx: WsContext, _message: dict[str, Any]) -> None:
    if ctx.goal_service is None:
        await send_error(ctx.websocket, "goals are not configured")
        return
    try:
        if not ctx.app.state.allow_test_events:
            raise ValueError("test events are disabled in config (app.enable_test_events)")
        deleted = await asyncio.to_thread(ctx.goal_service.database.delete_all_test_events)
        session_revenue = getattr(ctx.app.state, "session_revenue", None)
        if session_revenue is not None:
            await session_revenue.remove_test_events()
        if deleted:
            from ..routes import _after_goal_change

            await _after_goal_change(ctx.goal_service, ctx.broadcaster, ctx.app)
        await ctx.websocket.send_json({"type": "test_event.deleted", "count": deleted})
    except (TypeError, ValueError) as exc:
        await send_error(ctx.websocket, exc)
