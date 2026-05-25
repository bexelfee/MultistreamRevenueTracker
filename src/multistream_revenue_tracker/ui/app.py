from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..app_paths import package_static_path
from ..platforms.supported_currencies import supported_currency_codes
from .goal_broadcast import GoalBroadcaster
from .routes import router
from .ws_auth import generate_ui_token

if TYPE_CHECKING:
    from ..goals.goal_service import GoalService
    from ..monitors.monitor_coordinator import MonitorCoordinator
    from ..monitors.monitor_status import MonitorStatusRegistry
    from ..platforms.patreon_runtime import PatreonRuntime
    from ..revenue.session_revenue import SessionRevenueStore
    from ..services.subathon_service import SubathonService


def create_app(
    goal_service: GoalService | None = None,
    subathon_service: SubathonService | None = None,
    event_queue: asyncio.Queue | None = None,
    allow_test_events: bool = False,
    patreon_runtime: PatreonRuntime | None = None,
    monitor_registry: MonitorStatusRegistry | None = None,
    monitor_coordinator: MonitorCoordinator | None = None,
    shutdown_event: asyncio.Event | None = None,
    stop_requested: asyncio.Event | None = None,
    session_revenue: SessionRevenueStore | None = None,
    session_handles=None,
    user_config: dict | None = None,
    config_path: Path | None = None,
    ui_port: int | None = None,
    ui_token: str | None = None,
    require_ws_token: bool = False,
) -> FastAPI:
    app = FastAPI(title="Multistream Revenue Tracker")
    # Optional per-session WS token (config: app.require_ws_token). When enabled,
    # the token rotates each launch and is embedded in overlay URLs; when disabled
    # (default), OBS sources can keep stable URLs across restarts.
    app.state.require_ws_token = bool(require_ws_token)
    if require_ws_token:
        app.state.ui_token = ui_token or generate_ui_token()
    else:
        app.state.ui_token = ui_token or ""
    app.state.ui_port = ui_port
    app.state.goal_service = goal_service
    app.state.subathon_service = subathon_service
    app.state.event_queue = event_queue
    app.state.allow_test_events = allow_test_events
    app.state.patreon_runtime = patreon_runtime
    app.state.monitor_registry = monitor_registry
    app.state.monitor_coordinator = monitor_coordinator
    app.state.shutdown_event = shutdown_event
    app.state.stop_requested = stop_requested
    app.state.dashboard_shutdown_grace_task = None
    app.state.session_revenue = session_revenue
    app.state.session_handles = session_handles
    app.state.user_config = user_config or {}
    app.state.bar_appearance = (user_config or {}).get("bar_appearance")
    app.state.timer_appearance = (user_config or {}).get("timer_appearance")
    app.state.progress_effects = (user_config or {}).get("progress_effects")
    app.state.config_path = config_path
    app.state.supported_currencies = list(supported_currency_codes())
    broadcaster = GoalBroadcaster()
    app.state.goal_broadcaster = broadcaster
    if goal_service is not None:

        async def on_progress_changed() -> None:
            await broadcaster.broadcast_progress(
                goal_service,
                bar_appearance=getattr(app.state, "bar_appearance", None),
                progress_effects=getattr(app.state, "progress_effects", None),
            )
            if session_revenue is not None:
                await broadcaster.broadcast_session_revenue(session_revenue)

        goal_service.add_progress_listener(on_progress_changed)

    if subathon_service is not None:

        async def on_subathon_changed() -> None:
            await broadcaster.broadcast_subathon(subathon_service)

        subathon_service.add_listener(on_subathon_changed)

    if goal_service is not None:

        async def on_monitor_status_changed() -> None:
            await broadcaster.broadcast_state(
                goal_service, patreon_runtime,
                monitor_registry=monitor_registry, session_revenue=session_revenue,
                user_config=app.state.user_config, allow_test_events=app.state.allow_test_events,
                supported_currencies=app.state.supported_currencies,
                bar_appearance=app.state.bar_appearance,
                timer_appearance=app.state.timer_appearance,
                progress_effects=app.state.progress_effects,
                subathon_service=subathon_service,
            )

        if monitor_registry is not None:
            monitor_registry.set_on_change(on_monitor_status_changed)

        if session_revenue is not None:
            async def on_session_revenue_changed() -> None:
                await broadcaster.broadcast_session_revenue(session_revenue)

            session_revenue.set_on_change(on_session_revenue_changed)

    app.include_router(router)
    # Mount /assets/ for dashboard.css, dashboard.js, progress_effects.css, etc.
    # `package_static_path` resolves correctly under both source and frozen
    # (PyInstaller) layouts so the same routes work in dev and release builds.
    static_dir = package_static_path("ui", "static")
    app.mount(
        "/assets",
        StaticFiles(directory=str(static_dir)),
        name="assets",
    )
    return app
