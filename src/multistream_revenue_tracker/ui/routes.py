from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from .goal_broadcast import GoalBroadcaster, build_ws_state
from .log_broadcast import subscribe
from .templates import templates
from .ws import WsContext, dispatch
from .ws._helpers import user_facing_error_message
from .ws_auth import authorize_websocket

# Cap inbound WebSocket frames at 64 KB. The dashboard never legitimately sends
# anything close to this — the largest payload is a few-hundred-byte config
# patch. The cap defends against accidental or malicious memory amplification.
MAX_WS_MESSAGE_BYTES = 64 * 1024

router = APIRouter()
LOGGER = logging.getLogger(__name__)

# Delay shutdown after the last dashboard WebSocket drops so brief network blips
# or browser tab throttling (keepalive ping timeout) can reconnect without killing
# monitors mid-stream.
DASHBOARD_DISCONNECT_GRACE_SECONDS = 45

async def _cancel_dashboard_shutdown_grace(app) -> None:
    task = getattr(app.state, "dashboard_shutdown_grace_task", None)
    if task is None or task.done():
        app.state.dashboard_shutdown_grace_task = None
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    app.state.dashboard_shutdown_grace_task = None


async def _schedule_shutdown_if_still_alone(app) -> None:
    await _cancel_dashboard_shutdown_grace(app)
    stop_requested = getattr(app.state, "stop_requested", None)
    if stop_requested is None or stop_requested.is_set():
        return

    async def _grace() -> None:
        try:
            await asyncio.sleep(DASHBOARD_DISCONNECT_GRACE_SECONDS)
        except asyncio.CancelledError:
            return
        broadcaster: GoalBroadcaster = app.state.goal_broadcaster
        if await broadcaster.dashboard_connection_count() > 0:
            return
        if stop_requested.is_set():
            return
        ui_context = getattr(app.state, "ui_context", None)
        if ui_context is not None and ui_context.restart_requested:
            return
        LOGGER.info(
            "no dashboard client reconnected within %ss; starting graceful shutdown",
            DASHBOARD_DISCONNECT_GRACE_SECONDS,
        )
        if ui_context is not None:
            ui_context.restart_requested = False
        stop_requested.set()

    app.state.dashboard_shutdown_grace_task = asyncio.create_task(_grace())


async def _request_shutdown_if_last_dashboard_client(app) -> None:
    """Shut down when the last dashboard WebSocket disconnects (after a grace period)."""
    stop_requested = getattr(app.state, "stop_requested", None)
    if stop_requested is None or stop_requested.is_set():
        return
    ui_context = getattr(app.state, "ui_context", None)
    if ui_context is not None and ui_context.restart_requested:
        return
    broadcaster: GoalBroadcaster = app.state.goal_broadcaster
    if await broadcaster.dashboard_connection_count() > 0:
        await _cancel_dashboard_shutdown_grace(app)
        return
    LOGGER.info(
        "last dashboard client disconnected; shutdown in %ss unless a client reconnects",
        DASHBOARD_DISCONNECT_GRACE_SECONDS,
    )
    await _schedule_shutdown_if_still_alone(app)


def _template_context(request: Request, **extra) -> dict:
    """Common template context — embeds ui_token when WS token auth is enabled."""
    require_token = getattr(request.app.state, "require_ws_token", False)
    ui_token = getattr(request.app.state, "ui_token", "") if require_token else ""
    base = {"ui_token": ui_token, "require_ws_token": require_token}
    base.update(extra)
    return base


@router.get("/")
async def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html",
        _template_context(request, title="Multistream Revenue Tracker"),
    )


@router.get("/overlay")
async def overlay(request: Request):
    return templates.TemplateResponse(
        request, "overlay.html",
        _template_context(request, title="Goal overlay"),
    )


@router.get("/timer")
async def timer_overlay(request: Request):
    return templates.TemplateResponse(
        request, "timer_overlay.html",
        _template_context(request, title="Subathon timer overlay"),
    )


async def _accept_ws(websocket: WebSocket) -> bool:
    """Validate the auth token + Origin before accepting the WebSocket upgrade."""
    require_token = getattr(websocket.app.state, "require_ws_token", False)
    expected_token = getattr(websocket.app.state, "ui_token", None) or None
    expected_port = getattr(websocket.app.state, "ui_port", None)
    await websocket.accept()
    return await authorize_websocket(
        websocket,
        expected_token=expected_token,
        expected_port=expected_port,
        require_token=require_token,
    )


async def _receive_ws_text(websocket: WebSocket) -> str:
    """Receive a text frame and reject any that exceed MAX_WS_MESSAGE_BYTES."""
    raw = await websocket.receive_text()
    if len(raw.encode("utf-8", errors="ignore")) > MAX_WS_MESSAGE_BYTES:
        # Reject silently rather than disconnecting so a stuck/buggy client
        # cannot flood logs by retrying. Caller treats this as "ignore".
        LOGGER.warning("dropping oversize websocket frame (%d bytes)", len(raw))
        await websocket.send_json({"type": "error", "message": "message too large"})
        return ""
    return raw


@router.websocket("/ws/overlay")
async def overlay_websocket(websocket: WebSocket):
    """Progress-only WebSocket for OBS browser source (no logs)."""
    if not await _accept_ws(websocket):
        return
    goal_service = websocket.app.state.goal_service
    broadcaster: GoalBroadcaster = websocket.app.state.goal_broadcaster
    await broadcaster.register(websocket, role="overlay")
    try:
        if goal_service is not None:
            bar_appearance = getattr(websocket.app.state, "bar_appearance", None)
            progress_effects = getattr(websocket.app.state, "progress_effects", None)
            user_config = getattr(websocket.app.state, "user_config", None)
            payload = build_ws_state(
                goal_service,
                bar_appearance=bar_appearance,
                progress_effects=progress_effects,
                user_config=user_config,
            )
            await websocket.send_json({
                "type": "state",
                "progress": payload.get("progress"),
                "bar_appearance": payload.get("bar_appearance"),
                "progress_effects": payload.get("progress_effects"),
            })
        while True:
            raw = await _receive_ws_text(websocket)
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await broadcaster.unregister(websocket)


@router.websocket("/ws/timer")
async def timer_overlay_websocket(websocket: WebSocket):
    """Subathon timer WebSocket for OBS browser source."""
    if not await _accept_ws(websocket):
        return
    subathon_service = websocket.app.state.subathon_service
    broadcaster: GoalBroadcaster = websocket.app.state.goal_broadcaster
    await broadcaster.register(websocket, role="timer_overlay")
    try:
        if subathon_service is not None:
            timer_appearance = getattr(websocket.app.state, "timer_appearance", None)
            await websocket.send_json({
                "type": "state",
                "subathon": subathon_service.snapshot(),
                "timer_appearance": timer_appearance,
            })
        while True:
            raw = await _receive_ws_text(websocket)
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await broadcaster.unregister(websocket)


@router.websocket("/ws")
async def ui_websocket(websocket: WebSocket):
    if not await _accept_ws(websocket):
        return
    goal_service = websocket.app.state.goal_service
    broadcaster: GoalBroadcaster = websocket.app.state.goal_broadcaster
    await broadcaster.register(websocket, role="dashboard")
    await _cancel_dashboard_shutdown_grace(websocket.app)

    history, queue, unsubscribe = subscribe()
    try:
        if goal_service is not None:
            await broadcaster.send_state(
                websocket, goal_service,
                websocket.app.state.patreon_runtime,
                monitor_registry=websocket.app.state.monitor_registry,
                session_revenue=websocket.app.state.session_revenue,
                user_config=websocket.app.state.user_config,
                allow_test_events=bool(websocket.app.state.allow_test_events),
                supported_currencies=list(websocket.app.state.supported_currencies),
                subathon_service=getattr(websocket.app.state, "subathon_service", None),
                timer_appearance=getattr(websocket.app.state, "timer_appearance", None),
            )
        for line in history:
            await websocket.send_json({"type": "log", "line": line})

        async def forward_logs() -> None:
            while True:
                line = await queue.get()
                if websocket.client_state != WebSocketState.CONNECTED:
                    return
                await websocket.send_json({"type": "log", "line": line})

        forward_task = asyncio.create_task(forward_logs())
        try:
            while True:
                raw = await _receive_ws_text(websocket)
                if not raw:
                    continue
                await _handle_client_message(websocket, raw, goal_service, broadcaster, websocket.app)
        except WebSocketDisconnect:
            pass
        finally:
            forward_task.cancel()
            await asyncio.gather(forward_task, return_exceptions=True)
    finally:
        unsubscribe()
        await broadcaster.unregister(websocket)
        await _request_shutdown_if_last_dashboard_client(websocket.app)


async def _handle_client_message(
    websocket: WebSocket,
    raw: str,
    goal_service,
    broadcaster: GoalBroadcaster,
    app,
) -> None:
    """Parse one inbound frame and dispatch to the registered ws handler.

    All per-domain logic lives in ``ui/ws/handlers_*.py``; this function only
    enforces JSON-object envelope shape and turns unhandled exceptions into a
    scrubbed ``error`` payload so a buggy handler cannot tear down the socket.
    """
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        await websocket.send_json({"type": "error", "message": "expected JSON message"})
        return
    if not isinstance(message, dict):
        await websocket.send_json({"type": "error", "message": "expected JSON object"})
        return

    ctx = WsContext(
        websocket=websocket,
        goal_service=goal_service,
        broadcaster=broadcaster,
        app=app,
    )
    try:
        handled = await dispatch(ctx, message)
    except (TypeError, ValueError, FileNotFoundError) as exc:
        await websocket.send_json(
            {"type": "error", "message": user_facing_error_message(exc)},
        )
        return
    except Exception:  # pragma: no cover - defensive: scrub and log
        LOGGER.exception("unhandled exception in ws handler")
        await websocket.send_json(
            {"type": "error", "message": "internal error processing message"},
        )
        return

    if not handled:
        LOGGER.debug("unhandled websocket message type=%r", message.get("type"))


async def _broadcast_progress_update(goal_service, broadcaster: GoalBroadcaster, app) -> None:
    if goal_service is None or app is None:
        return
    await broadcaster.broadcast_progress(
        goal_service,
        bar_appearance=getattr(app.state, "bar_appearance", None),
        progress_effects=getattr(app.state, "progress_effects", None),
    )


async def _after_goal_change(goal_service, broadcaster: GoalBroadcaster, app=None) -> None:
    patreon_runtime = app.state.patreon_runtime if app is not None else None
    monitor_registry = app.state.monitor_registry if app is not None else None
    session_revenue = app.state.session_revenue if app is not None else None
    user_config = app.state.user_config if app is not None else None
    allow_test_events = bool(app.state.allow_test_events) if app is not None else False
    bar_appearance = getattr(app.state, "bar_appearance", None) if app is not None else None
    subathon_service = getattr(app.state, "subathon_service", None) if app is not None else None
    timer_appearance = getattr(app.state, "timer_appearance", None) if app is not None else None
    progress_effects = getattr(app.state, "progress_effects", None) if app is not None else None
    await broadcaster.broadcast_state(
        goal_service, patreon_runtime,
        monitor_registry=monitor_registry, session_revenue=session_revenue,
        user_config=user_config, allow_test_events=allow_test_events,
        supported_currencies=list(app.state.supported_currencies) if app is not None else None,
        bar_appearance=bar_appearance,
        timer_appearance=timer_appearance,
        progress_effects=progress_effects,
        subathon_service=subathon_service,
    )


