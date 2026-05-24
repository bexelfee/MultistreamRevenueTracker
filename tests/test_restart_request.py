from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from multistream_revenue_tracker.config_store import save_user_config
from multistream_revenue_tracker.main import main


@pytest.mark.asyncio
async def test_main_restarts_in_process_until_session_exits(tmp_path):
    config_path = tmp_path / "config.json"
    save_user_config(
        config_path,
        {
            "app": {
                "enable_twitch": False,
                "enable_youtube": False,
                "enable_patreon": False,
                "base_currency": "EUR",
                "ui_port": 8080,
            },
            "twitch": {"channel_name": ""},
        },
    )

    calls = 0

    async def fake_session(path, *, open_browser):
        nonlocal calls
        calls += 1
        return calls == 1

    with patch("multistream_revenue_tracker.main._run_app_session", fake_session), patch(
        "multistream_revenue_tracker.main.asyncio.sleep", new_callable=AsyncMock
    ):
        await main(config_path)

    assert calls == 2
