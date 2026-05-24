"""subathon.set_time, subathon.play, subathon.pause, subathon.save_settings."""

from __future__ import annotations

import asyncio
from typing import Any

from ...config_store import normalized_user_config_for_ui, save_user_config
from ...services.subathon_service import parse_time_parts
from ._helpers import send_error
from .context import WsContext
from .registry import ws_handler


def _service_or_raise(ctx: WsContext):
    service = getattr(ctx.app.state, "subathon_service", None)
    if service is None:
        raise ValueError("subathon timer is not available")
    return service


@ws_handler("subathon.set_time")
async def handle_set_time(ctx: WsContext, message: dict[str, Any]) -> None:
    try:
        service = _service_or_raise(ctx)
        total = message.get("total_seconds")
        if total is not None:
            seconds = parse_time_parts(total_seconds=int(total))
        else:
            seconds = parse_time_parts(
                hours=message.get("hours"),
                minutes=message.get("minutes"),
                seconds=message.get("seconds"),
            )
        await asyncio.to_thread(service.set_remaining_seconds, seconds)
        await asyncio.to_thread(service.reset_watermark)
        await ctx.broadcaster.broadcast_subathon(service)
    except (TypeError, ValueError, FileNotFoundError) as exc:
        await send_error(ctx.websocket, exc)


@ws_handler("subathon.play")
async def handle_play(ctx: WsContext, _message: dict[str, Any]) -> None:
    try:
        service = _service_or_raise(ctx)
        await asyncio.to_thread(service.set_running, True)
        await ctx.broadcaster.broadcast_subathon(service)
    except (TypeError, ValueError, FileNotFoundError) as exc:
        await send_error(ctx.websocket, exc)


@ws_handler("subathon.pause")
async def handle_pause(ctx: WsContext, _message: dict[str, Any]) -> None:
    try:
        service = _service_or_raise(ctx)
        await asyncio.to_thread(service.set_running, False)
        await ctx.broadcaster.broadcast_subathon(service)
    except (TypeError, ValueError, FileNotFoundError) as exc:
        await send_error(ctx.websocket, exc)


@ws_handler("subathon.save_settings")
async def handle_save_settings(ctx: WsContext, message: dict[str, Any]) -> None:
    try:
        service = _service_or_raise(ctx)
        config_path = getattr(ctx.app.state, "config_path", None)
        if config_path is None:
            raise ValueError("config is not available")
        points = int(message.get("points", 0))
        seconds = int(message.get("seconds", 0))
        if points < 1 or seconds < 1:
            raise ValueError("points and seconds must be at least 1")
        normalized = save_user_config(
            config_path, {"app": {"subathon_points": points, "subathon_seconds": seconds}},
        )
        await asyncio.to_thread(service.set_conversion, points, seconds)
        ctx.app.state.user_config = normalized_user_config_for_ui(normalized)
        await ctx.broadcaster.broadcast_subathon(service)
        await ctx.websocket.send_json({
            "type": "subathon.settings.saved",
            "message": "Subathon settings saved.",
        })
    except (TypeError, ValueError, FileNotFoundError) as exc:
        await send_error(ctx.websocket, exc)
