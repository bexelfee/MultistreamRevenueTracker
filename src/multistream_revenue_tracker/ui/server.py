from __future__ import annotations

import asyncio
import logging
import os
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn

from .app import create_app
from .goal_broadcast import GoalBroadcaster

if TYPE_CHECKING:
    from ..goals.goal_service import GoalService
    from ..monitors.monitor_coordinator import MonitorCoordinator
    from ..monitors.monitor_status import MonitorStatusRegistry
    from ..revenue.session_revenue import SessionRevenueStore
    from ..services.subathon_service import SubathonService

LOGGER = logging.getLogger(__name__)


@dataclass
class WebUiContext:
    """Holds UI handles so main can broadcast shutdown before stopping the server."""

    broadcaster: GoalBroadcaster | None = None
    restart_requested: bool = False
    _server: uvicorn.Server | None = field(default=None, repr=False)
    _serve_task: asyncio.Task | None = field(default=None, repr=False)

    async def stop_server(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._serve_task is not None:
            await self._serve_task


def _browser_url(host: str, port: int) -> str:
    if host in ("0.0.0.0", "::"):
        return f"http://127.0.0.1:{port}/"
    if host == "::1":
        return f"http://[::1]:{port}/"
    return f"http://{host}:{port}/"


async def _open_browser(url: str) -> None:
    await asyncio.sleep(0.6)
    try:
        await asyncio.to_thread(webbrowser.open, url)
        LOGGER.info("opened web UI in browser: %s", url)
    except Exception:
        LOGGER.exception("failed to open web UI in browser")


async def run_web_server(
    host: str,
    port: int,
    ui_stop: asyncio.Event,
    goal_service: GoalService | None = None,
    subathon_service: SubathonService | None = None,
    event_queue: asyncio.Queue | None = None,
    allow_test_events: bool = False,
    patreon_runtime=None,
    monitor_registry: MonitorStatusRegistry | None = None,
    monitor_coordinator: MonitorCoordinator | None = None,
    session_revenue: SessionRevenueStore | None = None,
    session_handles=None,
    shutdown_event: asyncio.Event | None = None,
    stop_requested: asyncio.Event | None = None,
    ui_context: WebUiContext | None = None,
    user_config: dict | None = None,
    config_path: Path | None = None,
    open_browser: bool = True,
    require_ws_token: bool = False,
) -> None:
    app = create_app(
        goal_service=goal_service,
        subathon_service=subathon_service,
        event_queue=event_queue,
        allow_test_events=allow_test_events,
        patreon_runtime=patreon_runtime,
        monitor_registry=monitor_registry,
        monitor_coordinator=monitor_coordinator,
        shutdown_event=shutdown_event,
        stop_requested=stop_requested,
        session_revenue=session_revenue,
        session_handles=session_handles,
        user_config=user_config,
        config_path=config_path,
        ui_port=port,
        require_ws_token=require_ws_token,
    )
    ctx = ui_context if ui_context is not None else WebUiContext()
    ctx.broadcaster = app.state.goal_broadcaster
    app.state.ui_context = ctx

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        # Long streams: give the browser more time to answer protocol pings when the
        # tab is backgrounded or the machine is busy (default 20s/20s is tight).
        ws_ping_interval=30.0,
        ws_ping_timeout=60.0,
    )
    server = uvicorn.Server(config)
    ctx._server = server
    url = _browser_url(host, port)
    LOGGER.info("web UI listening on %s", url)
    if require_ws_token:
        LOGGER.debug("dashboard WS token auth enabled for this session")
    ctx._serve_task = asyncio.create_task(server.serve())
    suppress_browser = os.environ.get("MRT_NO_BROWSER", "").strip().lower() in ("1", "true", "yes")
    if open_browser and not suppress_browser:
        asyncio.create_task(_open_browser(url))
    try:
        await ui_stop.wait()
    finally:
        await ctx.stop_server()
        LOGGER.info("web UI stopped")
