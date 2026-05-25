"""Mutable handles for reloading configuration without restarting the process."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..monitors import patreon_monitor, streamlabs_monitor, twitch_monitor, youtube_monitor
from ..config import AppConfig, load_config
from ..monitors.monitor_coordinator import (
    MonitorCoordinator,
    MonitorCoroutineFactory,
    PatreonConnectHandler,
    YOUTUBE_CONNECT_CANCELLED,
    YoutubeConnectHandler,
)
from ..monitors.monitor_status import (
    MonitorAuthCancelled,
    MonitorStatusRegistry,
    build_initial_status,
    format_monitor_auth_error,
)
from ..platforms.patreon_client import (
    PATREON_CONNECT_CANCELLED,
    PatreonApiError,
    PatreonClient,
    ensure_patreon_token,
)
from ..log_scrubbing import register_from_app_config
from ..platforms.patreon_runtime import PatreonRuntime

LOGGER = logging.getLogger(__name__)


@dataclass
class SessionHandles:
    """References shared by the web UI and config reload after save."""

    config_path: Path
    queue: asyncio.Queue
    shutdown_event: asyncio.Event
    registry: MonitorStatusRegistry
    coordinator: MonitorCoordinator
    patreon_runtime: PatreonRuntime
    _connect_patreon: PatreonConnectHandler | None = field(default=None, repr=False)
    _connect_youtube: YoutubeConnectHandler | None = field(default=None, repr=False)

    def set_connect_patreon(self, handler: PatreonConnectHandler | None) -> None:
        self._connect_patreon = handler
        self.coordinator.set_patreon_connect(handler)

    def set_connect_youtube(self, handler: YoutubeConnectHandler | None) -> None:
        self._connect_youtube = handler
        self.coordinator.set_youtube_connect(handler)

    async def reload_after_config_save(self) -> AppConfig:
        """Apply saved config.json to coordinator and registry."""
        prev_cfg = self.coordinator._app_cfg
        prev_streamlabs_token = (
            prev_cfg.streamlabs.socket_api_token.strip() if prev_cfg is not None else ""
        )
        app_cfg = await asyncio.to_thread(load_config, self.config_path)
        register_from_app_config(app_cfg)
        self.patreon_runtime._initial_campaign_id = app_cfg.patreon.campaign_id.strip()
        self.coordinator.set_app_cfg(app_cfg)
        if prev_streamlabs_token != app_cfg.streamlabs.socket_api_token.strip():
            row = self.registry.get_status("streamlabs")
            if row is not None and row.status in ("active", "connecting", "authenticating"):
                self.coordinator.request_disconnect("streamlabs")
        await self._sync_registry()
        self._sync_factories(app_cfg)
        self.set_connect_patreon(self._build_connect_patreon(app_cfg))
        self.set_connect_youtube(self._build_connect_youtube(app_cfg))
        return app_cfg

    async def _sync_registry(self) -> None:
        for row in build_initial_status():
            current = self.registry.get_status(row.id)
            if current is None:
                await self.registry.ensure_monitor_async(row)
                continue
            if current.status == "active" and self.coordinator.is_running(row.id):
                continue
            if current.status in ("authenticating", "connecting"):
                continue
            if current.status != row.status or current.detail != row.detail:
                await self.registry.set_status_async(row.id, row.status, row.detail)

    def _sync_factories(self, app_cfg: AppConfig) -> None:
        enabled = self._build_factories(app_cfg)
        for monitor_id in self.coordinator.factory_ids():
            if monitor_id not in enabled:
                self.coordinator.remove_factory(monitor_id)
        for monitor_id, factory in enabled.items():
            self.coordinator.register_factory(monitor_id, factory)

    def _build_factories(self, app_cfg: AppConfig) -> dict[str, MonitorCoroutineFactory]:
        """Always register all four monitor factories.

        Monitors decide internally whether to run (e.g. Streamlabs returns
        idle when no token is set). We used to gate them on phantom
        ``enable_*`` flags that were always True; those have been removed.
        """
        runtime = self.patreon_runtime
        return {
            "twitch": lambda: twitch_monitor.await_twitch_events(
                self.queue,
                self.shutdown_event,
                app_cfg.twitch,
                app_cfg.app,
                self.registry,
            ),
            "youtube": lambda: youtube_monitor.await_youtube_events(
                self.queue,
                self.shutdown_event,
                app_cfg.youtube,
                app_cfg.app,
                self.registry,
            ),
            "patreon": lambda: patreon_monitor.await_patreon_events(
                self.queue,
                self.shutdown_event,
                app_cfg.patreon,
                app_cfg.app,
                runtime,
                self.registry,
            ),
            "streamlabs": lambda: streamlabs_monitor.await_streamlabs_events(
                self.queue,
                self.shutdown_event,
                app_cfg.streamlabs,
                app_cfg.app,
                self.registry,
            ),
        }

    def _build_connect_patreon(self, app_cfg: AppConfig) -> PatreonConnectHandler:
        runtime = self.patreon_runtime

        async def connect_patreon() -> str | None:
            runtime.load_error = None
            try:
                token = await ensure_patreon_token(app_cfg.patreon)
                catalog_client = PatreonClient(app_cfg.patreon, token)
                try:
                    await runtime.load_catalog(catalog_client)
                finally:
                    await catalog_client.aclose()
            except PatreonApiError as exc:
                if "cancelled" in str(exc).lower():
                    LOGGER.info("Patreon connect cancelled")
                    return PATREON_CONNECT_CANCELLED
                LOGGER.exception("Patreon connect failed")
                msg = format_monitor_auth_error("Patreon", exc)
                runtime.load_error = msg
                return msg
            except Exception as exc:
                LOGGER.exception("Patreon connect failed")
                msg = format_monitor_auth_error("Patreon", exc)
                if runtime.load_error is None:
                    runtime.load_error = msg
                return runtime.load_error or msg
            if runtime.load_error:
                return runtime.load_error
            return None

        return connect_patreon

    def _build_connect_youtube(self, app_cfg: AppConfig) -> YoutubeConnectHandler:
        async def connect_youtube() -> str | None:
            try:
                await asyncio.to_thread(
                    youtube_monitor.load_youtube_credentials,
                    app_cfg.youtube,
                    None,
                    None,
                    None,
                )
            except MonitorAuthCancelled:
                LOGGER.info("YouTube connect cancelled")
                return YOUTUBE_CONNECT_CANCELLED
            except RuntimeError as exc:
                LOGGER.exception("YouTube connect failed")
                return format_monitor_auth_error("YouTube", exc)
            except Exception as exc:
                LOGGER.exception("YouTube connect failed")
                return format_monitor_auth_error("YouTube", exc)
            return None

        return connect_youtube
