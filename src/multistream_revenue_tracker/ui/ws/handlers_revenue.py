"""revenue_event.invalidate / validate."""

from __future__ import annotations

import asyncio
from typing import Any

from ._helpers import send_error
from .context import WsContext
from .registry import ws_handler


@ws_handler("revenue_event.invalidate", "revenue_event.validate")
async def handle_invalidate_or_validate(ctx: WsContext, message: dict[str, Any]) -> None:
    if ctx.goal_service is None:
        await send_error(ctx.websocket, "goals are not configured")
        return
    try:
        event_id = int(message.get("event_id", 0))
        if event_id <= 0:
            raise ValueError("event_id is required")
        session_revenue = getattr(ctx.app.state, "session_revenue", None)
        if message["type"] == "revenue_event.invalidate":
            updated = await asyncio.to_thread(
                ctx.goal_service.invalidate_revenue_event, event_id,
            )
        else:
            updated = await asyncio.to_thread(
                ctx.goal_service.validate_revenue_event, event_id,
            )
        if session_revenue is not None:
            await session_revenue.update_by_id(event_id, updated)
        from ..routes import _after_goal_change

        await _after_goal_change(ctx.goal_service, ctx.broadcaster, ctx.app)
    except (TypeError, ValueError) as exc:
        await send_error(ctx.websocket, exc)
