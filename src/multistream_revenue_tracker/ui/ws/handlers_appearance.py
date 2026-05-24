"""bar_appearance.save, timer_appearance.save, progress_effects.save/preview.

The three "save appearance" handlers used to repeat the same load → save →
extract → broadcast → reply sequence with only the schema strings different.
Collapsed here into one parametric ``_handle_appearance_save`` helper.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ...appearance.bar_appearance import extract_bar_appearance
from ...config_store import (
    normalized_user_config_for_ui,
    save_bar_appearance,
    save_progress_effects,
    save_timer_appearance,
)
from ...appearance.progress_effects import (
    EFFECT_NONE,
    GOAL_COMPLETE_EFFECTS,
    POINTS_ADDED_EFFECTS,
    extract_progress_effects,
)
from ...appearance.timer_appearance import extract_timer_appearance
from ._helpers import require_dict, send_error
from .context import WsContext
from .registry import ws_handler

_VALID_GOAL_EFFECT_IDS = frozenset(item["id"] for item in GOAL_COMPLETE_EFFECTS)
_VALID_POINTS_EFFECT_IDS = frozenset(item["id"] for item in POINTS_ADDED_EFFECTS)


@dataclass(frozen=True)
class _AppearanceSchema:
    """One row per appearance domain — the only thing that varies across the
    three handlers we used to have."""

    message_field: str
    save_fn: Callable[..., dict]  # save_user_config-like writer
    extract_fn: Callable[[dict | None], dict]
    broadcaster_method: str  # GoalBroadcaster method name
    state_attr: str  # app.state attribute to set
    saved_message_type: str
    saved_message: str
    post_save: Callable[[WsContext, dict], Awaitable[None]] | None = None


def _appearance_handler(
    schema: _AppearanceSchema,
) -> Callable[[WsContext, dict[str, Any]], Awaitable[None]]:
    async def handler(ctx: WsContext, message: dict[str, Any]) -> None:
        try:
            config_path = getattr(ctx.app.state, "config_path", None)
            if config_path is None:
                raise ValueError("config is not available")
            payload = require_dict(message.get(schema.message_field), schema.message_field)
            normalized = schema.save_fn(config_path, payload)
            saved = schema.extract_fn(normalized.get("app"))
            setattr(ctx.app.state, schema.state_attr, saved)
            if ctx.app.state.user_config is not None:
                ctx.app.state.user_config = normalized_user_config_for_ui(normalized)
            broadcast = getattr(ctx.broadcaster, schema.broadcaster_method)
            await broadcast(saved)
            if schema.post_save is not None:
                await schema.post_save(ctx, saved)
            await ctx.websocket.send_json({
                "type": schema.saved_message_type,
                schema.message_field: saved,
                "message": schema.saved_message,
            })
        except (TypeError, ValueError, FileNotFoundError) as exc:
            await send_error(ctx.websocket, exc)

    return handler


async def _bar_post_save(ctx: WsContext, _saved: dict) -> None:
    # Bar appearance changes affect computed progress payload (fill color
    # etc.) so re-broadcast full state to dashboard subscribers.
    from ..routes import _after_goal_change  # local import to avoid cycle

    if ctx.goal_service is not None:
        await _after_goal_change(ctx.goal_service, ctx.broadcaster, ctx.app)


async def _timer_post_save(ctx: WsContext, saved: dict) -> None:
    service = getattr(ctx.app.state, "subathon_service", None)
    if service is None:
        raise ValueError("subathon timer is not available")
    await asyncio.to_thread(service.set_show_days, saved["show_days"])
    await ctx.broadcaster.broadcast_subathon(service)


_BAR_SCHEMA = _AppearanceSchema(
    message_field="bar_appearance",
    save_fn=save_bar_appearance,
    extract_fn=extract_bar_appearance,
    broadcaster_method="broadcast_bar_appearance",
    state_attr="bar_appearance",
    saved_message_type="bar_appearance.saved",
    saved_message="Bar appearance saved.",
    post_save=_bar_post_save,
)

_TIMER_SCHEMA = _AppearanceSchema(
    message_field="timer_appearance",
    save_fn=save_timer_appearance,
    extract_fn=extract_timer_appearance,
    broadcaster_method="broadcast_timer_appearance",
    state_attr="timer_appearance",
    saved_message_type="timer_appearance.saved",
    saved_message="Timer appearance saved.",
    post_save=_timer_post_save,
)

_EFFECTS_SCHEMA = _AppearanceSchema(
    message_field="progress_effects",
    save_fn=save_progress_effects,
    extract_fn=extract_progress_effects,
    broadcaster_method="broadcast_progress_effects",
    state_attr="progress_effects",
    saved_message_type="progress_effects.saved",
    saved_message="Progress effects saved.",
)


handle_bar_save = ws_handler("bar_appearance.save")(_appearance_handler(_BAR_SCHEMA))
handle_timer_save = ws_handler("timer_appearance.save")(_appearance_handler(_TIMER_SCHEMA))
handle_effects_save = ws_handler("progress_effects.save")(_appearance_handler(_EFFECTS_SCHEMA))


@ws_handler("progress_effects.preview")
async def handle_effects_preview(ctx: WsContext, message: dict[str, Any]) -> None:
    channel = str(message.get("channel", "")).strip()
    if channel not in ("goal", "points"):
        await send_error(ctx.websocket, "channel must be goal or points")
        return
    effect_id = str(message.get("effect_id", EFFECT_NONE)).strip() or EFFECT_NONE
    allowed = _VALID_GOAL_EFFECT_IDS if channel == "goal" else _VALID_POINTS_EFFECT_IDS
    if effect_id not in allowed:
        await send_error(ctx.websocket, "unknown effect_id")
        return
    await ctx.broadcaster.broadcast_progress_effect_preview(channel=channel, effect_id=effect_id)
