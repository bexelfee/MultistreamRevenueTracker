"""goal.create/select/delete/points_change, progress.refresh."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...revenue.events import parse_iso_datetime
from ._helpers import send_error
from .context import WsContext
from .registry import ws_handler


def _parse_started_at(value) -> datetime | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("started_at must be an ISO-8601 string")
    parsed = parse_iso_datetime(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _need_goal_service(ctx: WsContext) -> bool:
    if ctx.goal_service is None:
        return False
    return True


@ws_handler("goal.create")
async def handle_goal_create(ctx: WsContext, message: dict[str, Any]) -> None:
    if not _need_goal_service(ctx):
        await send_error(ctx.websocket, "goals are not configured")
        return
    try:
        name = str(message.get("name", "")).strip()
        target_points = int(message.get("target_points", 0))
        started_at = _parse_started_at(message.get("started_at"))
        ctx.goal_service.create_goal(
            name, target_points, started_at, select=bool(message.get("select", True)),
        )
        from ..routes import _after_goal_change

        await _after_goal_change(ctx.goal_service, ctx.broadcaster, ctx.app)
    except (TypeError, ValueError) as exc:
        await send_error(ctx.websocket, exc)


@ws_handler("goal.select")
async def handle_goal_select(ctx: WsContext, message: dict[str, Any]) -> None:
    if not _need_goal_service(ctx):
        await send_error(ctx.websocket, "goals are not configured")
        return
    try:
        goal_id = str(message.get("goal_id", "")).strip()
        if not goal_id:
            raise ValueError("goal_id is required")
        ctx.goal_service.select_goal(goal_id)
        from ..routes import _after_goal_change

        await _after_goal_change(ctx.goal_service, ctx.broadcaster, ctx.app)
    except (TypeError, ValueError) as exc:
        await send_error(ctx.websocket, exc)


@ws_handler("goal.delete")
async def handle_goal_delete(ctx: WsContext, message: dict[str, Any]) -> None:
    if not _need_goal_service(ctx):
        await send_error(ctx.websocket, "goals are not configured")
        return
    try:
        goal_id = str(message.get("goal_id", "")).strip()
        if not goal_id:
            raise ValueError("goal_id is required")
        ctx.goal_service.delete_goal(goal_id)
        from ..routes import _after_goal_change

        await _after_goal_change(ctx.goal_service, ctx.broadcaster, ctx.app)
    except (TypeError, ValueError) as exc:
        await send_error(ctx.websocket, exc)


def _parse_points_amount(raw: Any) -> float:
    if isinstance(raw, bool):
        raise ValueError("amount must be a number")
    if isinstance(raw, (int, float)):
        return round(max(0.0, float(raw)), 2)
    if isinstance(raw, str) and raw.strip():
        try:
            return round(max(0.0, float(raw.strip())), 2)
        except ValueError as exc:
            raise ValueError("amount must be a number") from exc
    raise ValueError("amount must be a number")


@ws_handler("goal.points_change")
async def handle_points_change(ctx: WsContext, message: dict[str, Any]) -> None:
    if not _need_goal_service(ctx):
        await send_error(ctx.websocket, "goals are not configured")
        return
    try:
        amount = _parse_points_amount(message.get("amount", 0))
        add = bool(message.get("add"))
        ctx.goal_service.apply_points_change(amount, add=add)
        from ..routes import _after_goal_change, _broadcast_progress_update

        await _broadcast_progress_update(ctx.goal_service, ctx.broadcaster, ctx.app)
        await _after_goal_change(ctx.goal_service, ctx.broadcaster, ctx.app)
    except (TypeError, ValueError) as exc:
        await send_error(ctx.websocket, exc)


@ws_handler("goal.points_reset")
async def handle_points_reset(ctx: WsContext, _message: dict[str, Any]) -> None:
    if not _need_goal_service(ctx):
        await send_error(ctx.websocket, "goals are not configured")
        return
    try:
        ctx.goal_service.reset_active_goal_points()
        from ..routes import _after_goal_change, _broadcast_progress_update

        await _broadcast_progress_update(ctx.goal_service, ctx.broadcaster, ctx.app)
        await _after_goal_change(ctx.goal_service, ctx.broadcaster, ctx.app)
    except (TypeError, ValueError) as exc:
        await send_error(ctx.websocket, exc)


@ws_handler("progress.refresh")
async def handle_progress_refresh(ctx: WsContext, _message: dict[str, Any]) -> None:
    if not _need_goal_service(ctx):
        await send_error(ctx.websocket, "goals are not configured")
        return
    progress = ctx.goal_service.compute_progress()
    payload = {"type": "progress", **progress.to_dict()}
    bar_appearance = getattr(ctx.app.state, "bar_appearance", None)
    progress_effects = getattr(ctx.app.state, "progress_effects", None)
    if bar_appearance is not None:
        payload["bar_appearance"] = bar_appearance
    if progress_effects is not None:
        payload["progress_effects"] = progress_effects
    await ctx.websocket.send_json(payload)
