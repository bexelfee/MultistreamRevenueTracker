"""Tests for deferred monitor connect at session startup."""

from pathlib import Path

from multistream_revenue_tracker.config import (
    AppConfig,
    AppSettings,
    PatreonConfig,
    StreamlabsConfig,
    TwitchConfig,
    YoutubeConfig,
)
from multistream_revenue_tracker.monitors.monitor_status import NOT_CONNECTED_DETAIL, build_initial_status
from multistream_revenue_tracker.platforms.patreon_runtime import PatreonRuntime


def _minimal_app_config():
    root = Path(".")
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


def test_patreon_enabled_starts_idle_without_catalog_at_boot():
    runtime = PatreonRuntime(Path("config.json"))
    rows = build_initial_status(_minimal_app_config(), runtime)
    patreon = next(r for r in rows if r.id == "patreon")
    assert patreon.status == "idle"
    assert runtime.load_error is None
    assert not runtime.catalog.campaigns
