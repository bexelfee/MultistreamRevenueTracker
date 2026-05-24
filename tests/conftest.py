"""Shared pytest fixtures and collection hooks."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Any

import pytest
from starlette.websockets import WebSocketState

from multistream_revenue_tracker.bundled_credentials import has_bundled_developer_credentials
from multistream_revenue_tracker.config import (
    AppConfig,
    AppSettings,
    PatreonConfig,
    StreamlabsConfig,
    TwitchConfig,
    YoutubeConfig,
)


def make_app_config(
    tmp_path: Path,
    *,
    streamlabs_token: str = "",
    twitch_channel: str = "channel",
) -> AppConfig:
    """Minimal AppConfig used by many unit tests. Avoids duplicating the
    constructor wall across test modules."""
    return AppConfig(
        twitch=TwitchConfig("id", "secret", twitch_channel),
        youtube=YoutubeConfig(
            token_path=tmp_path / "yt_token.json",
            oauth_client_config={"installed": {"client_id": "x", "client_secret": "y"}},
        ),
        patreon=PatreonConfig(
            "pid", "psecret", "http://localhost/cb",
            tmp_path / "patreon_token.json", "", 30,
        ),
        streamlabs=StreamlabsConfig(socket_api_token=streamlabs_token),
        app=AppSettings(
            log_level="INFO",
            log_chat_messages_for_testing=False,
            database_path=tmp_path / "db.db",
            ui_host="127.0.0.1",
            ui_port=8080,
            goals_directory=tmp_path / "goals",
            point_rules_path=tmp_path / "point_rules.json",
            exchange_rates_path=tmp_path / "exchange_rates.json",
            base_currency="EUR",
            enable_test_events=False,
            twitch_sub_resub_dedupe_seconds=300,
        ),
    )


class FakeWebSocket:
    """Stand-in WebSocket for testing handlers without uvicorn / TestClient."""

    def __init__(self, app: Any | None = None) -> None:
        self.app = app
        self.client_state = WebSocketState.CONNECTED
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.fixture
def fake_ws() -> FakeWebSocket:
    return FakeWebSocket()

# OAuth / build env vars cleared so unit tests control credential resolution.
_OAUTH_ENV_VARS = (
    "TWITCH_CLIENT_ID",
    "TWITCH_CLIENT_SECRET",
    "PATREON_CLIENT_ID",
    "PATREON_CLIENT_SECRET",
    "PATREON_SECRET",
    "YOUTUBE_CLIENT_SECRETS_PATH",
    "YOUTUBE_OAUTH_CLIENT_JSON",
    "STREAMLABS_SOCKET_TOKEN",
)


@pytest.fixture(autouse=True)
def _clear_oauth_env(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Keep unit credential tests independent of the developer's shell (not E2E)."""
    path = str(request.node.path).replace("\\", "/")
    if "/tests/e2e/" in path or request.node.get_closest_marker("e2e"):
        return
    for name in _OAUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _user_requested_e2e() -> bool:
    """True if the pytest invocation explicitly targets the E2E suite.

    Mixing E2E tests (which keep a session-scoped Playwright loop alive) with
    `pytest-asyncio` unit tests inside the same process triggers a known
    "Cannot run the event loop while another loop is running" error during
    teardown. We guard against this by auto-deselecting E2E tests unless the
    user opted in via `-m`, `-k`, or a path/file containing `e2e`.
    """
    argv = " ".join(sys.argv).lower()
    if "e2e" in argv:
        return True
    return False


_SKIP_WHEN_BUNDLED = frozenset({
    "test_resolve_twitch_from_env",
    "test_resolve_youtube_from_json_env",
    "test_resolve_youtube_from_secrets_path_env",
    "test_resolve_youtube_missing_path_raises",
    "test_bootstrap_resolves_developer_credentials_from_env",
    "test_load_app_config_uses_bootstrap_when_missing",
})

_SKIP_BUNDLED_REASON = (
    "bundled developer credentials are present in bundled_credentials.py; "
    "env-based credential resolution tests are skipped"
)


def pytest_configure(config) -> None:  # noqa: ARG001
    if has_bundled_developer_credentials():
        warnings.warn(
            "bundled_credentials.py contains developer OAuth credentials. "
            "Restore the empty template after a release build (see README). "
            "Some unit tests that assume env-only resolution are skipped.",
            UserWarning,
            stacklevel=1,
        )


def pytest_collection_modifyitems(config, items) -> None:  # noqa: ARG001
    """Auto-deselect E2E tests unless the user explicitly targets them."""
    if has_bundled_developer_credentials():
        skip = pytest.mark.skip(reason=_SKIP_BUNDLED_REASON)
        for item in items:
            if item.name in _SKIP_WHEN_BUNDLED:
                item.add_marker(skip)

    if _user_requested_e2e():
        return
    deselected: list = []
    keep: list = []
    for item in items:
        path = str(item.path).replace("\\", "/")
        if "/tests/e2e/" in path:
            deselected.append(item)
        else:
            keep.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = keep
        # Surface the deselect via the terminal reporter so it doesn't look
        # like the E2E suite "just disappeared". Run `pytest -m e2e` or
        # `pytest tests/e2e/` to actually execute them.
        reporter = config.pluginmanager.getplugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(
                f"E2E tests auto-deselected ({len(deselected)} skipped): "
                "pass '-m e2e' or 'tests/e2e/' to run them.",
                yellow=True,
            )
