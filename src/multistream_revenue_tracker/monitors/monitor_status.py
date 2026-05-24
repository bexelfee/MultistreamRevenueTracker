from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..config import AppConfig
from .monitor_constants import MONITOR_AUTH_TIMEOUT_SECONDS
from ..platforms.patreon_runtime import PatreonRuntime

LOGGER = logging.getLogger(__name__)

MonitorStatusValue = str  # idle | authenticating | connecting | active | error

MONITOR_IDLE_DETAILS: dict[str, str] = {
    "youtube": "No live youtube broadcast found",
    "twitch": "Stopped",
    "patreon": "Stopped",
    "streamlabs": "Stopped",
}

NOT_CONNECTED_DETAIL = "Not connected"
DISCONNECTED_DETAIL = "Disconnected"


class MonitorAuthCancelled(Exception):
    """Monitor authorisation aborted (Cancel, shutdown, or tab close)."""


def format_monitor_auth_error(label: str, exc: BaseException) -> str:
    """Turn OAuth/setup failures into short UI-friendly messages."""
    message = str(exc).strip() or exc.__class__.__name__
    lowered = message.lower()
    if "access_denied" in lowered or "denied" in lowered or "cancel" in lowered:
        return f"{label} authorisation was denied. Try connecting again."
    if "timeout" in lowered or "timed out" in lowered:
        return f"{label} authorisation timed out. Try connecting again."
    if "invalid_client" in lowered or "invalid_grant" in lowered:
        return f"{label} authorisation failed: check client credentials in config.json."
    return f"{label} authorisation failed: {message}"


def format_monitor_error(label: str, exc: BaseException) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    lowered = message.lower()
    if "no live youtube broadcast" in lowered:
        return message
    if f"{label.lower()} authorisation" in lowered:
        return message
    auth_markers = (
        "access_denied",
        "denied",
        "cancel",
        "timeout",
        "timed out",
        "invalid_client",
        "invalid_grant",
        "oauth",
    )
    if any(marker in lowered for marker in auth_markers):
        return format_monitor_auth_error(label, exc)
    return f"{label} monitor failed: {message}"


@dataclass(frozen=True)
class MonitorStatus:
    id: str
    label: str
    status: MonitorStatusValue
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
        }


def build_initial_status(
    app_cfg: AppConfig | None = None,
    patreon_runtime: PatreonRuntime | None = None,
) -> list[MonitorStatus]:
    del app_cfg, patreon_runtime
    return [
        MonitorStatus("twitch", "Twitch", "idle", NOT_CONNECTED_DETAIL),
        MonitorStatus("youtube", "YouTube", "idle", NOT_CONNECTED_DETAIL),
        MonitorStatus("patreon", "Patreon", "idle", NOT_CONNECTED_DETAIL),
        MonitorStatus("streamlabs", "Streamlabs", "idle", NOT_CONNECTED_DETAIL),
    ]


class MonitorStatusRegistry:
    def __init__(self, initial: list[MonitorStatus] | None = None) -> None:
        self._lock = asyncio.Lock()
        self._monitors: dict[str, MonitorStatus] = {}
        if initial:
            for row in initial:
                self._monitors[row.id] = row

    def snapshot(self) -> list[dict[str, Any]]:
        return [row.to_dict() for row in self._ordered()]

    def get_status(self, monitor_id: str) -> MonitorStatus | None:
        return self._monitors.get(monitor_id)

    def ensure_monitor(self, row: MonitorStatus) -> None:
        if row.id not in self._monitors:
            self._monitors[row.id] = row
            self._notify()

    async def ensure_monitor_async(self, row: MonitorStatus) -> None:
        async with self._lock:
            self.ensure_monitor(row)

    def set_status(self, monitor_id: str, status: MonitorStatusValue, detail: str | None = None) -> None:
        current = self._monitors.get(monitor_id)
        if current is None:
            LOGGER.warning("unknown monitor_id %r in set_status", monitor_id)
            return
        updated = MonitorStatus(current.id, current.label, status, detail)
        self._monitors[monitor_id] = updated
        self._notify()

    async def set_status_async(self, monitor_id: str, status: MonitorStatusValue, detail: str | None = None) -> None:
        async with self._lock:
            self.set_status(monitor_id, status, detail)

    def _ordered(self) -> list[MonitorStatus]:
        order = ("twitch", "youtube", "patreon", "streamlabs")
        return [self._monitors[key] for key in order if key in self._monitors]

    def set_on_change(self, callback: Callable[[], Awaitable[None]] | None) -> None:
        self._on_change = callback

    def _notify(self) -> None:
        callback = getattr(self, "_on_change", None)
        if callback is None:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(callback())
        except RuntimeError:
            pass


async def run_monitor(
    name: str,
    coroutine,
    registry: MonitorStatusRegistry,
    shutdown_event: asyncio.Event,
) -> None:
    try:
        await coroutine
    except asyncio.CancelledError:
        LOGGER.info("%s monitor cancelled", name)
        current = registry.get_status(name)
        if current is not None and current.status in ("authenticating", "connecting"):
            await registry.set_status_async(name, "idle", DISCONNECTED_DETAIL)
        raise
    except MonitorAuthCancelled:
        LOGGER.info("%s monitor authorisation cancelled", name)
        await registry.set_status_async(name, "idle", DISCONNECTED_DETAIL)
        return
    except Exception as exc:
        LOGGER.exception("%s monitor failed", name)
        current = registry.get_status(name)
        label = current.label if current else name
        await registry.set_status_async(name, "error", format_monitor_error(label, exc))
    else:
        detail = MONITOR_IDLE_DETAILS.get(name, "Stopped")
        await registry.set_status_async(name, "idle", detail)
    finally:
        LOGGER.info("%s monitor finished", name)
