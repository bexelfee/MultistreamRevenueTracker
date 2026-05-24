import threading
import time
from unittest.mock import patch

import pytest

from multistream_revenue_tracker.config import PatreonConfig
from multistream_revenue_tracker.platforms.patreon_client import (
    PatreonOAuthCancelled,
    _run_oauth_flow,
    cancel_pending_oauth,
)


def _config(tmp_path) -> PatreonConfig:
    return PatreonConfig(
        client_id="id",
        client_secret="secret",
        redirect_uri="http://localhost:8765/callback",
        token_path=tmp_path / "token.json",
        campaign_id="",
        poll_interval_seconds=30,
    )


def test_cancel_pending_oauth_interrupts_flow_quickly(tmp_path):
    config = _config(tmp_path)

    def slow_browser(*_args, **_kwargs):
        time.sleep(0.05)

    with patch("multistream_revenue_tracker.platforms.patreon_client.webbrowser.open", slow_browser):
        errors: list[BaseException] = []

        def run() -> None:
            try:
                _run_oauth_flow(config)
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        time.sleep(0.15)
        cancel_pending_oauth()
        thread.join(timeout=3.0)

    assert not thread.is_alive()
    assert errors and isinstance(errors[0], PatreonOAuthCancelled)


def test_run_oauth_flow_raises_when_cancelled_before_callback(tmp_path):
    config = _config(tmp_path)

    with patch("multistream_revenue_tracker.platforms.patreon_client.webbrowser.open"):
        errors: list[BaseException] = []

        def run() -> None:
            try:
                _run_oauth_flow(config)
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        time.sleep(0.1)
        cancel_pending_oauth()
        thread.join(timeout=3.0)

    assert not thread.is_alive()
    assert errors and isinstance(errors[0], PatreonOAuthCancelled)
