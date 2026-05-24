from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from ..config import AppConfig
from .monitor_constants import (
    MONITOR_AUTH_TIMEOUT_SECONDS,
    MONITOR_DISCONNECT_CANCEL_TIMEOUT_SECONDS,
    MONITOR_SHUTDOWN_CANCEL_TIMEOUT_SECONDS,
)
from ..platforms.patreon_client import PATREON_CONNECT_CANCELLED, cancel_pending_oauth
from .streamlabs_monitor import request_streamlabs_stop
from .youtube_monitor import cancel_pending_youtube_oauth
from .monitor_status import (
    DISCONNECTED_DETAIL,
    MonitorStatusRegistry,
    format_monitor_auth_error,
    run_monitor,
)

LOGGER = logging.getLogger(__name__)

MonitorCoroutineFactory = Callable[[], Coroutine[Any, Any, None]]
PatreonConnectHandler = Callable[[], Awaitable[str | None]]
YoutubeConnectHandler = Callable[[], Awaitable[str | None]]
YOUTUBE_CONNECT_CANCELLED = "__youtube_connect_cancelled__"


class MonitorCoordinator:
    """Starts monitor tasks on user connect and supports per-monitor disconnect/restart."""

    def __init__(
        self,
        registry: MonitorStatusRegistry,
        shutdown_event: asyncio.Event,
        *,
        factories: dict[str, MonitorCoroutineFactory],
        patreon_connect: PatreonConnectHandler | None = None,
        youtube_connect: YoutubeConnectHandler | None = None,
        app_cfg: AppConfig | None = None,
    ) -> None:
        self._registry = registry
        self._shutdown = shutdown_event
        self._factories = dict(factories)
        self._patreon_connect = patreon_connect
        self._youtube_connect = youtube_connect
        self._app_cfg = app_cfg
        self._tasks: dict[str, asyncio.Task] = {}
        self._connect_ops: dict[str, asyncio.Task] = {}
        self._restart_queue: asyncio.Queue[str] = asyncio.Queue()
        self._restart_loop_task: asyncio.Task | None = None

    def set_app_cfg(self, app_cfg: AppConfig) -> None:
        self._app_cfg = app_cfg

    def start_restart_loop(self) -> None:
        self._restart_loop_task = asyncio.create_task(
            self._run_restart_loop(),
            name="monitor-restart-loop",
        )

    def request_restart(self, monitor_id: str) -> None:
        self._restart_queue.put_nowait(monitor_id)

    def register_factory(self, monitor_id: str, factory: MonitorCoroutineFactory) -> None:
        self._factories[monitor_id] = factory

    def remove_factory(self, monitor_id: str) -> None:
        self._factories.pop(monitor_id, None)

    def set_patreon_connect(self, handler: PatreonConnectHandler | None) -> None:
        self._patreon_connect = handler

    def set_youtube_connect(self, handler: YoutubeConnectHandler | None) -> None:
        self._youtube_connect = handler

    def factory_ids(self) -> list[str]:
        return list(self._factories.keys())

    def task_names(self) -> list[str]:
        return list(self._tasks.keys())

    def is_running(self, monitor_id: str) -> bool:
        task = self._tasks.get(monitor_id)
        return task is not None and not task.done()

    def is_connecting(self, monitor_id: str) -> bool:
        op = self._connect_ops.get(monitor_id)
        return op is not None and not op.done()

    def request_connect(self, monitor_id: str) -> None:
        """Start connect in the background so the UI WebSocket stays responsive."""
        if self.is_connecting(monitor_id):
            return

        async def _run() -> None:
            try:
                await self.connect(monitor_id)
            except asyncio.CancelledError:
                await self._abort_connect(monitor_id)
                raise
            finally:
                self._connect_ops.pop(monitor_id, None)

        self._connect_ops[monitor_id] = asyncio.create_task(
            _run(),
            name=f"{monitor_id}-connect-op",
        )

    def request_disconnect(self, monitor_id: str) -> None:
        """Stop a monitor in the background so the UI WebSocket stays responsive."""

        async def _run() -> None:
            await self.disconnect(monitor_id)

        asyncio.create_task(_run(), name=f"{monitor_id}-disconnect-op")

    async def connect(self, monitor_id: str) -> str | None:
        """Authorise (if needed) and start a monitor. Returns an error message or None."""
        try:
            return await asyncio.wait_for(
                self._connect_body(monitor_id),
                timeout=MONITOR_AUTH_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            await self._abort_connect(monitor_id)
            label = self._monitor_label(monitor_id)
            msg = format_monitor_auth_error(label, TimeoutError("authorisation timed out"))
            await self._registry.set_status_async(monitor_id, "error", msg)
            return msg

    async def _connect_body(self, monitor_id: str) -> str | None:
        current = self._registry.get_status(monitor_id)
        if current is None:
            return f"Unknown monitor {monitor_id!r}"

        if current.status in ("authenticating", "connecting"):
            return None
        if self.is_running(monitor_id):
            return None

        preflight = self._preflight_connect(monitor_id)
        if preflight:
            await self._registry.set_status_async(monitor_id, "error", preflight)
            return preflight

        if monitor_id == "patreon":
            if self._patreon_connect is None:
                return "Patreon is not configured"
            await self._registry.set_status_async(monitor_id, "authenticating", None)
            err = await self._patreon_connect()
            if err == PATREON_CONNECT_CANCELLED:
                await self._abort_connect(monitor_id)
                return None
            if err:
                await self._registry.set_status_async(monitor_id, "error", err)
                return err

        if monitor_id == "youtube":
            if self._youtube_connect is None:
                return "YouTube is not configured"
            await self._registry.set_status_async(monitor_id, "authenticating", None)
            err = await self._youtube_connect()
            if err == YOUTUBE_CONNECT_CANCELLED:
                await self._abort_connect(monitor_id)
                return None
            if err:
                await self._registry.set_status_async(monitor_id, "error", err)
                return err

        factory = self._factories.get(monitor_id)
        if factory is None:
            return f"Monitor {monitor_id!r} is not available"

        await self._cancel_task(monitor_id)
        await self._registry.set_status_async(monitor_id, "authenticating", None)
        self._spawn(monitor_id)
        return await self._wait_for_connect_result(monitor_id)

    async def disconnect(self, monitor_id: str) -> str | None:
        """Stop a running monitor without deleting stored OAuth tokens."""
        current = self._registry.get_status(monitor_id)
        if current is None:
            return f"Unknown monitor {monitor_id!r}"

        connect_op = self._connect_ops.pop(monitor_id, None)
        if connect_op is not None and not connect_op.done():
            connect_op.cancel()
            await self._gather_with_timeout(
                connect_op,
                timeout=MONITOR_DISCONNECT_CANCEL_TIMEOUT_SECONDS,
                label=f"{monitor_id}-connect-op",
            )

        await self._abort_connect(monitor_id)
        return None

    async def cancel_all(
        self,
        *,
        task_join_timeout: float | None = MONITOR_SHUTDOWN_CANCEL_TIMEOUT_SECONDS,
    ) -> None:
        cancel_pending_oauth()
        cancel_pending_youtube_oauth()
        if self._restart_loop_task is not None:
            self._restart_loop_task.cancel()
            await self._gather_with_timeout(
                self._restart_loop_task,
                timeout=task_join_timeout,
                label="monitor-restart-loop",
            )
            self._restart_loop_task = None
        for monitor_id in list(self._connect_ops.keys()):
            op = self._connect_ops.pop(monitor_id, None)
            if op is not None and not op.done():
                op.cancel()
                await self._gather_with_timeout(
                    op,
                    timeout=task_join_timeout,
                    label=f"{monitor_id}-connect-op",
                )
        for monitor_id in list(self._tasks.keys()):
            await self._cancel_task(monitor_id, join_timeout=task_join_timeout)
        self._tasks.clear()

    async def restart(self, monitor_id: str) -> str | None:
        """Cancel a running task (if any) and connect again. Returns an error message or None."""
        current = self._registry.get_status(monitor_id)
        if current is None:
            return f"Unknown monitor {monitor_id!r}"

        await self._cancel_task(monitor_id)
        await self._registry.set_status_async(monitor_id, "idle", DISCONNECTED_DETAIL)
        return await self.connect(monitor_id)

    def _monitor_label(self, monitor_id: str) -> str:
        row = self._registry.get_status(monitor_id)
        return row.label if row else monitor_id

    def _preflight_connect(self, monitor_id: str) -> str | None:
        if self._app_cfg is None:
            return None
        app = self._app_cfg
        if monitor_id == "twitch":
            if not app.twitch.client_id or not app.twitch.client_secret:
                return (
                    "Twitch developer credentials are not configured. "
                    "Use a release build or set TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET (see README)."
                )
            if not app.twitch.channel_name:
                return "Set your Twitch username on the dashboard before connecting."
        elif monitor_id == "youtube":
            if not app.youtube.oauth_client_config:
                return (
                    "YouTube developer credentials are not configured. Set YOUTUBE_CLIENT_SECRETS_PATH "
                    "or YOUTUBE_OAUTH_CLIENT_JSON (see README), or use a release build."
                )
        elif monitor_id == "patreon":
            if not app.patreon.client_id or not app.patreon.client_secret:
                return (
                    "Patreon developer credentials are not configured. "
                    "Use a release build or set PATREON_CLIENT_ID and PATREON_CLIENT_SECRET (see README)."
                )
        elif monitor_id == "streamlabs":
            if not app.streamlabs.socket_api_token:
                return (
                    "Add your Streamlabs Socket API token on the Configuration tab "
                    "(Streamlabs → Settings → API Settings → API Tokens), then save and connect."
                )
        return None

    async def _abort_connect(self, monitor_id: str) -> None:
        if monitor_id == "patreon":
            cancel_pending_oauth()
        elif monitor_id == "youtube":
            cancel_pending_youtube_oauth()
        elif monitor_id == "streamlabs":
            request_streamlabs_stop()
        await self._registry.set_status_async(monitor_id, "idle", DISCONNECTED_DETAIL)
        await self._cancel_task(
            monitor_id,
            join_timeout=MONITOR_DISCONNECT_CANCEL_TIMEOUT_SECONDS,
        )

    async def _gather_with_timeout(
        self,
        task: asyncio.Task,
        *,
        timeout: float | None,
        label: str,
    ) -> None:
        gather = asyncio.gather(task, return_exceptions=True)
        if timeout is None:
            await gather
            return
        try:
            await asyncio.wait_for(gather, timeout=timeout)
        except asyncio.TimeoutError:
            LOGGER.warning(
                "%s did not stop within %.1fs during shutdown; continuing",
                label,
                timeout,
            )

    async def _cancel_task(self, monitor_id: str, *, join_timeout: float | None = None) -> None:
        existing = self._tasks.get(monitor_id)
        if existing is not None and not existing.done():
            existing.cancel()
            await self._gather_with_timeout(
                existing,
                timeout=join_timeout,
                label=f"{monitor_id} monitor",
            )
            if not existing.done():
                await self._registry.set_status_async(monitor_id, "idle", DISCONNECTED_DETAIL)
        self._tasks.pop(monitor_id, None)

    def _spawn(self, monitor_id: str) -> None:
        factory = self._factories[monitor_id]
        self._tasks[monitor_id] = asyncio.create_task(
            run_monitor(monitor_id, factory(), self._registry, self._shutdown),
            name=monitor_id,
        )

    async def _wait_for_connect_result(self, monitor_id: str) -> str | None:
        """Wait until the monitor reaches active or error (or disconnect)."""
        while not self._shutdown.is_set():
            row = self._registry.get_status(monitor_id)
            if row is None:
                return None
            if row.status == "active":
                return None
            if row.status == "error":
                return row.detail
            if row.status == "idle":
                return None
            task = self._tasks.get(monitor_id)
            if task is not None and task.done():
                exc = task.exception()
                if exc is not None and row.status not in ("active", "error"):
                    label = self._monitor_label(monitor_id)
                    msg = format_monitor_auth_error(label, exc)
                    await self._registry.set_status_async(monitor_id, "error", msg)
                    return msg
                return row.detail if row.status == "error" else None
            await asyncio.sleep(0.2)
        return None

    async def _run_restart_loop(self) -> None:
        try:
            while not self._shutdown.is_set():
                try:
                    monitor_id = await asyncio.wait_for(self._restart_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                try:
                    err = await self.restart(monitor_id)
                    if err:
                        await self._registry.set_status_async(monitor_id, "error", err)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    LOGGER.exception("monitor restart failed for %s", monitor_id)
                    await self._registry.set_status_async(monitor_id, "error", str(exc))
        except asyncio.CancelledError:
            LOGGER.info("monitor restart loop cancelled")
            raise
