import asyncio
import threading
import time

import pytest

from multistream_revenue_tracker.config import (
    AppConfig,
    AppSettings,
    PatreonConfig,
    StreamlabsConfig,
    TwitchConfig,
    YoutubeConfig,
)
from multistream_revenue_tracker.monitors.monitor_coordinator import MonitorCoordinator
from multistream_revenue_tracker.monitors.monitor_status import (
    DISCONNECTED_DETAIL,
    MonitorAuthCancelled,
    MonitorStatus,
    MonitorStatusRegistry,
)
from multistream_revenue_tracker.monitors import youtube_monitor as ym


def _minimal_app_config(tmp_path) -> AppConfig:
    root = tmp_path
    return AppConfig(
        twitch=TwitchConfig("id", "secret", "channel"),
        youtube=YoutubeConfig(
            token_path=root / "yt_token.json",
            oauth_client_config={"installed": {"client_id": "x", "client_secret": "y"}},
        ),
        patreon=PatreonConfig("pid", "psecret", "http://localhost/cb", root / "patreon_token.json", "", 30),
        streamlabs=StreamlabsConfig(socket_api_token=""),
        app=AppSettings(
            log_level="INFO",
            log_chat_messages_for_testing=False,
            database_path=root / "db.db",
            ui_host="127.0.0.1",
            ui_port=8080,
            goals_directory=root / "goals",
            point_rules_path=root / "point_rules.json",
            exchange_rates_path=root / "exchange_rates.json",
            base_currency="EUR",
            enable_test_events=False,
            twitch_sub_resub_dedupe_seconds=300,
        ),
    )


def _simulate_oauth_blocking(cancel: threading.Event, started: threading.Event) -> None:
    started.set()
    while not cancel.wait(timeout=0.05):
        pass


@pytest.mark.asyncio
async def test_disconnect_during_youtube_oauth_returns_idle_quickly(tmp_path):
    """Blocking OAuth in a worker thread; Cancel must update UI without waiting for the thread."""
    registry = MonitorStatusRegistry([
        MonitorStatus("youtube", "YouTube", "idle", None),
    ])
    shutdown = asyncio.Event()
    oauth_started = threading.Event()
    cancel = threading.Event()

    async def youtube_factory():
        loop = asyncio.get_running_loop()
        with ym._youtube_oauth_lock:
            ym._youtube_oauth_cancel = cancel
            ym._youtube_oauth_server = None
        await registry.set_status_async("youtube", "authenticating", None)
        try:
            await loop.run_in_executor(None, _simulate_oauth_blocking, cancel, oauth_started)
        except asyncio.CancelledError:
            raise
        raise MonitorAuthCancelled()

    coordinator = MonitorCoordinator(
        registry,
        shutdown,
        factories={"youtube": youtube_factory},
        app_cfg=_minimal_app_config(tmp_path),
    )

    async def youtube_connect():
        return None

    coordinator.set_youtube_connect(youtube_connect)
    coordinator.request_connect("youtube")
    await asyncio.wait_for(asyncio.to_thread(oauth_started.wait), timeout=2.0)

    started = time.monotonic()
    coordinator.request_disconnect("youtube")
    for _ in range(50):
        if registry.get_status("youtube").status == "idle":
            break
        await asyncio.sleep(0.05)
    elapsed = time.monotonic() - started

    assert registry.get_status("youtube").status == "idle"
    assert registry.get_status("youtube").detail == DISCONNECTED_DETAIL
    assert elapsed < 2.0
    assert cancel.is_set()
    shutdown.set()
    await coordinator.cancel_all()
