from pathlib import Path

import pytest

from multistream_revenue_tracker.config import load_bootstrap_config
from multistream_revenue_tracker.monitors.monitor_coordinator import MonitorCoordinator
from multistream_revenue_tracker.monitors.monitor_status import MonitorStatusRegistry, build_initial_status
from multistream_revenue_tracker.revenue.session_handles import SessionHandles


@pytest.mark.asyncio
async def test_sync_factories_always_registers_all_monitors(tmp_path: Path):
    config_path = tmp_path / "config.json"
    bootstrap = load_bootstrap_config(config_path)
    import asyncio

    queue = asyncio.Queue()
    shutdown = asyncio.Event()
    registry = MonitorStatusRegistry(build_initial_status())
    coordinator = MonitorCoordinator(registry, shutdown, factories={})
    patreon_runtime = __import__(
        "multistream_revenue_tracker.platforms.patreon_runtime", fromlist=["PatreonRuntime"]
    ).PatreonRuntime(config_path, "")
    youtube_runtime = __import__(
        "multistream_revenue_tracker.platforms.youtube_runtime", fromlist=["YoutubeRuntime"]
    ).YoutubeRuntime()
    handles = SessionHandles(
        config_path=config_path,
        queue=queue,
        shutdown_event=shutdown,
        registry=registry,
        coordinator=coordinator,
        patreon_runtime=patreon_runtime,
        youtube_runtime=youtube_runtime,
    )
    handles._sync_factories(bootstrap)
    assert set(coordinator.factory_ids()) == {"twitch", "youtube", "patreon", "streamlabs"}
