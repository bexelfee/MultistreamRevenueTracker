import asyncio

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
    MONITOR_AUTH_TIMEOUT_SECONDS,
    MonitorStatus,
    MonitorStatusRegistry,
)


def _minimal_app_config(tmp_path, *, streamlabs_token: str = "") -> AppConfig:
    root = tmp_path
    return AppConfig(
        twitch=TwitchConfig("id", "secret", "channel"),
        youtube=YoutubeConfig(
            token_path=root / "yt_token.json",
            oauth_client_config={"installed": {"client_id": "x", "client_secret": "y"}},
        ),
        patreon=PatreonConfig("pid", "psecret", "http://localhost/cb", root / "patreon_token.json", "", 30),
        streamlabs=StreamlabsConfig(socket_api_token=streamlabs_token),
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


@pytest.mark.asyncio
async def test_connect_spawns_task_and_disconnect_cancels():
    registry = MonitorStatusRegistry([
        MonitorStatus("twitch", "Twitch", "idle", None),
    ])
    shutdown = asyncio.Event()
    started = asyncio.Event()

    async def factory():
        await registry.set_status_async("twitch", "active", None)
        started.set()
        await shutdown.wait()

    coordinator = MonitorCoordinator(registry, shutdown, factories={"twitch": factory})
    assert coordinator.task_names() == []

    err = await coordinator.connect("twitch")
    assert err is None
    await asyncio.wait_for(started.wait(), timeout=2.0)
    assert registry.snapshot()[0]["status"] == "active"

    err = await coordinator.disconnect("twitch")
    assert err is None
    assert coordinator.task_names() == []
    assert registry.snapshot()[0]["status"] == "idle"
    assert registry.snapshot()[0]["detail"] == DISCONNECTED_DETAIL
    shutdown.set()
    await coordinator.cancel_all()


@pytest.mark.asyncio
async def test_restart_cancels_failed_task_and_respawns():
    registry = MonitorStatusRegistry([
        MonitorStatus("twitch", "Twitch", "idle", None),
    ])
    shutdown = asyncio.Event()
    attempts = {"n": 0}

    async def factory():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("connection failed")
        await registry.set_status_async("twitch", "active", None)
        await shutdown.wait()

    coordinator = MonitorCoordinator(registry, shutdown, factories={"twitch": factory})
    err = await coordinator.connect("twitch")
    assert err is not None
    assert "connection failed" in err
    assert attempts["n"] == 1
    assert registry.snapshot()[0]["status"] == "error"

    await coordinator.restart("twitch")
    new_task = coordinator._tasks["twitch"]
    assert not new_task.done()
    assert registry.snapshot()[0]["status"] in ("authenticating", "connecting", "active")
    shutdown.set()
    await coordinator.cancel_all()


@pytest.mark.asyncio
async def test_request_restart_processed_by_loop():
    registry = MonitorStatusRegistry([
        MonitorStatus("youtube", "YouTube", "error", "offline"),
    ])
    shutdown = asyncio.Event()
    started = asyncio.Event()

    async def factory():
        await registry.set_status_async("youtube", "active", None)
        started.set()
        await shutdown.wait()

    coordinator = MonitorCoordinator(registry, shutdown, factories={"youtube": factory})

    async def youtube_connect():
        return None

    coordinator.set_youtube_connect(youtube_connect)
    coordinator.start_restart_loop()
    coordinator.request_restart("youtube")
    await asyncio.wait_for(started.wait(), timeout=2.0)
    shutdown.set()
    await coordinator.cancel_all()


@pytest.mark.asyncio
async def test_connect_patreon_runs_prep_handler():
    registry = MonitorStatusRegistry([
        MonitorStatus("patreon", "Patreon", "idle", None),
    ])
    shutdown = asyncio.Event()
    prep_called = {"n": 0}

    async def patreon_connect():
        prep_called["n"] += 1
        return None

    async def factory():
        await registry.set_status_async("patreon", "active", None)
        await shutdown.wait()

    coordinator = MonitorCoordinator(
        registry,
        shutdown,
        factories={"patreon": factory},
        patreon_connect=patreon_connect,
    )
    err = await coordinator.connect("patreon")
    assert err is None
    assert prep_called["n"] == 1
    shutdown.set()
    await coordinator.cancel_all()


@pytest.mark.asyncio
async def test_connect_patreon_sets_authenticating_before_prep():
    registry = MonitorStatusRegistry([
        MonitorStatus("patreon", "Patreon", "idle", None),
    ])
    shutdown = asyncio.Event()
    seen_statuses: list[str] = []

    async def patreon_connect():
        row = registry.get_status("patreon")
        if row:
            seen_statuses.append(row.status)
        return "Patreon authorisation was denied. Try connecting again."

    coordinator = MonitorCoordinator(
        registry,
        shutdown,
        factories={"patreon": lambda: shutdown.wait()},
        patreon_connect=patreon_connect,
    )
    err = await coordinator.connect("patreon")
    assert err == "Patreon authorisation was denied. Try connecting again."
    assert "authenticating" in seen_statuses
    assert registry.snapshot()[0]["status"] == "error"
    assert registry.snapshot()[0]["detail"] == err
    shutdown.set()
    await coordinator.cancel_all()


@pytest.mark.asyncio
async def test_connect_times_out_when_patreon_prep_hangs(monkeypatch):
    monkeypatch.setattr(
        "multistream_revenue_tracker.monitors.monitor_coordinator.MONITOR_AUTH_TIMEOUT_SECONDS",
        0.3,
    )
    registry = MonitorStatusRegistry([
        MonitorStatus("patreon", "Patreon", "idle", None),
    ])
    shutdown = asyncio.Event()

    async def hang():
        await asyncio.sleep(1.0)

    coordinator = MonitorCoordinator(
        registry,
        shutdown,
        factories={"patreon": lambda: shutdown.wait()},
        patreon_connect=hang,
    )
    err = await coordinator.connect("patreon")
    assert err is not None
    assert "timed out" in err.lower()
    assert registry.snapshot()[0]["status"] == "error"
    shutdown.set()
    await coordinator.cancel_all()


@pytest.mark.asyncio
async def test_disconnect_during_authenticating_returns_idle(tmp_path):
    registry = MonitorStatusRegistry([
        MonitorStatus("twitch", "Twitch", "idle", None),
    ])
    shutdown = asyncio.Event()
    gate = asyncio.Event()

    async def slow_factory():
        await registry.set_status_async("twitch", "authenticating", None)
        await gate.wait()

    coordinator = MonitorCoordinator(
        registry,
        shutdown,
        factories={"twitch": slow_factory},
        app_cfg=_minimal_app_config(tmp_path),
    )
    connect_task = asyncio.create_task(coordinator.connect("twitch"))
    await asyncio.sleep(0.05)
    err = await coordinator.disconnect("twitch")
    assert err is None
    assert registry.snapshot()[0]["status"] == "idle"
    gate.set()
    await connect_task
    shutdown.set()
    await coordinator.cancel_all()


@pytest.mark.asyncio
async def test_connect_twitch_requires_channel_name(tmp_path):
    registry = MonitorStatusRegistry([
        MonitorStatus("twitch", "Twitch", "idle", None),
    ])
    shutdown = asyncio.Event()
    app_cfg = _minimal_app_config(tmp_path)
    app_cfg.twitch.channel_name = ""

    coordinator = MonitorCoordinator(
        registry,
        shutdown,
        factories={"twitch": lambda: shutdown.wait()},
        app_cfg=app_cfg,
    )
    err = await coordinator.connect("twitch")
    assert err is not None
    assert "twitch username" in err.lower()
    assert registry.snapshot()[0]["status"] == "error"
    shutdown.set()
    await coordinator.cancel_all()


@pytest.mark.asyncio
async def test_connect_streamlabs_requires_socket_token(tmp_path):
    registry = MonitorStatusRegistry([
        MonitorStatus("streamlabs", "Streamlabs", "idle", None),
    ])
    shutdown = asyncio.Event()

    async def factory():
        await shutdown.wait()

    coordinator = MonitorCoordinator(
        registry,
        shutdown,
        factories={"streamlabs": factory},
        app_cfg=_minimal_app_config(tmp_path, streamlabs_token=""),
    )
    err = await coordinator.connect("streamlabs")
    assert err is not None
    assert "Socket API token" in err
    assert registry.snapshot()[0]["status"] == "error"
    shutdown.set()
    await coordinator.cancel_all()


@pytest.mark.asyncio
async def test_parallel_connect_while_other_authenticating(tmp_path):
    registry = MonitorStatusRegistry([
        MonitorStatus("twitch", "Twitch", "idle", None),
        MonitorStatus("youtube", "YouTube", "idle", None),
    ])
    shutdown = asyncio.Event()
    gate = asyncio.Event()

    async def twitch_factory():
        await registry.set_status_async("twitch", "authenticating", None)
        await gate.wait()
        await registry.set_status_async("twitch", "active", None)
        await shutdown.wait()

    async def youtube_factory():
        await registry.set_status_async("youtube", "active", None)
        await shutdown.wait()

    coordinator = MonitorCoordinator(
        registry,
        shutdown,
        factories={"twitch": twitch_factory, "youtube": youtube_factory},
        app_cfg=_minimal_app_config(tmp_path),
    )

    async def youtube_connect():
        return None

    coordinator.set_youtube_connect(youtube_connect)
    twitch_task = asyncio.create_task(coordinator.connect("twitch"))
    await asyncio.sleep(0.05)
    assert registry.get_status("twitch").status == "authenticating"
    err_yt = await coordinator.connect("youtube")
    assert err_yt is None
    assert registry.get_status("youtube").status == "active"
    gate.set()
    await twitch_task
    shutdown.set()
    await coordinator.cancel_all()


@pytest.mark.asyncio
async def test_cancel_all_does_not_block_on_slow_monitor_shutdown():
    registry = MonitorStatusRegistry([
        MonitorStatus("twitch", "Twitch", "idle", None),
    ])
    shutdown = asyncio.Event()

    async def factory():
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(3600)
            raise

    coordinator = MonitorCoordinator(registry, shutdown, factories={"twitch": factory})
    coordinator._spawn("twitch")
    await asyncio.sleep(0.05)

    shutdown.set()
    started = asyncio.get_running_loop().time()
    await coordinator.cancel_all(task_join_timeout=0.2)
    elapsed = asyncio.get_running_loop().time() - started
    assert elapsed < 2.0
    assert coordinator.task_names() == []
    assert registry.snapshot()[0]["status"] == "idle"
