"""config.save, point_rules.save, patreon.campaign.select."""

from __future__ import annotations

import asyncio
from typing import Any

from ...config import load_config
from ...config_store import (
    load_raw_config,
    normalize_user_config,
    normalized_user_config_for_ui,
    save_user_config,
)
from ..ws_auth import generate_ui_token
from ._helpers import require_dict, send_error
from .context import WsContext
from .registry import ws_handler


def _apply_ws_auth_settings(app, *, require_ws_token: bool) -> None:
    app.state.require_ws_token = bool(require_ws_token)
    if app.state.require_ws_token:
        app.state.ui_token = generate_ui_token()
    else:
        app.state.ui_token = ""


@ws_handler("config.save")
async def handle_config_save(ctx: WsContext, message: dict[str, Any]) -> None:
    config_path = getattr(ctx.app.state, "config_path", None)
    if config_path is None:
        raise ValueError("config is not available")
    try:
        patch = require_dict(message.get("config"), "config")
        normalized = save_user_config(config_path, patch)
        ctx.app.state.user_config = normalized_user_config_for_ui(normalized)
        ctx.app.state.bar_appearance = ctx.app.state.user_config.get("bar_appearance")
        ctx.app.state.progress_effects = ctx.app.state.user_config.get("progress_effects")
        ctx.app.state.allow_test_events = bool(normalized["app"]["enable_test_events"])
        _apply_ws_auth_settings(ctx.app, require_ws_token=bool(normalized["app"].get("require_ws_token", False)))
        reload_message = "Saved successfully."
        try:
            session_handles = getattr(ctx.app.state, "session_handles", None)
            if session_handles is not None:
                app_cfg = await session_handles.reload_after_config_save()
            else:
                app_cfg = await asyncio.to_thread(load_config, config_path)
            ctx.app.state.patreon_runtime = (
                getattr(session_handles, "patreon_runtime", None)
                if session_handles else ctx.app.state.patreon_runtime
            )
            ctx.app.state.user_config = normalized_user_config_for_ui(
                normalize_user_config(load_raw_config(config_path)),
            )
            ctx.app.state.allow_test_events = app_cfg.app.enable_test_events
            _apply_ws_auth_settings(ctx.app, require_ws_token=app_cfg.app.require_ws_token)
        except (ValueError, FileNotFoundError) as exc:
            reload_message = (
                f"Configuration saved, but some settings could not be applied: {exc}"
            )
        if ctx.goal_service is not None:
            from ..routes import _after_goal_change  # avoid cycle

            await _after_goal_change(ctx.goal_service, ctx.broadcaster, ctx.app)
        await ctx.websocket.send_json({"type": "config.saved", "message": reload_message})
    except (TypeError, ValueError, FileNotFoundError) as exc:
        await send_error(ctx.websocket, exc)


@ws_handler("point_rules.save")
async def handle_point_rules_save(ctx: WsContext, message: dict[str, Any]) -> None:
    if ctx.goal_service is None:
        await send_error(ctx.websocket, "goals are not configured")
        return
    try:
        rules = require_dict(message.get("rules"), "rules")
        ctx.goal_service.save_rules(rules)
        from ..routes import _after_goal_change  # avoid cycle

        await _after_goal_change(ctx.goal_service, ctx.broadcaster, ctx.app)
    except (TypeError, ValueError) as exc:
        await send_error(ctx.websocket, exc)


@ws_handler("patreon.campaign.select")
async def handle_campaign_select(ctx: WsContext, message: dict[str, Any]) -> None:
    if ctx.goal_service is None:
        await send_error(ctx.websocket, "goals are not configured")
        return
    try:
        patreon_runtime = ctx.app.state.patreon_runtime
        if patreon_runtime is None:
            raise ValueError("Patreon is not enabled")
        campaign_id = str(message.get("campaign_id", "")).strip()
        if not campaign_id:
            raise ValueError("campaign_id is required")
        await patreon_runtime.set_active_campaign(campaign_id)
        from ..routes import _after_goal_change

        await _after_goal_change(ctx.goal_service, ctx.broadcaster, ctx.app)
    except (TypeError, ValueError) as exc:
        await send_error(ctx.websocket, exc)
