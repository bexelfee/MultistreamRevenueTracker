from pathlib import Path



from multistream_revenue_tracker.config import (
    AppConfig,
    AppSettings,
    PatreonConfig,
    StreamlabsConfig,
    TwitchConfig,
    YoutubeConfig,
)

from multistream_revenue_tracker.monitors.monitor_status import (

    NOT_CONNECTED_DETAIL,

    MonitorStatusRegistry,

    build_initial_status,

    format_monitor_auth_error,

    format_monitor_error,

)

from multistream_revenue_tracker.platforms.patreon_runtime import PatreonRuntime





def _app_config():

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

            database_path=root / "revenue_events.db",

            ui_host="127.0.0.1",

            ui_port=8080,

            goals_directory=root / "goals",

            point_rules_path=root / "point_rules.json",

            exchange_rates_path=root / "exchange_rates.json",

            base_currency="EUR",

            enable_test_events=True,

            twitch_sub_resub_dedupe_seconds=300,

        ),

    )





def test_build_initial_status_all_idle():

    rows = build_initial_status(_app_config(), PatreonRuntime(Path("config.json")))

    by_id = {row.id: row for row in rows}

    assert len(by_id) == 4

    for monitor_id in ("twitch", "youtube", "patreon", "streamlabs"):

        assert by_id[monitor_id].status == "idle"

        assert by_id[monitor_id].detail == NOT_CONNECTED_DETAIL





def test_format_monitor_auth_error_maps_denied_and_timeout():

    assert "denied" in format_monitor_auth_error("Twitch", RuntimeError("access_denied")).lower()

    assert "timed out" in format_monitor_auth_error("YouTube", RuntimeError("OAuth timed out")).lower()





def test_format_monitor_error_preserves_youtube_idle_message():

    assert format_monitor_error("YouTube", RuntimeError("No live youtube broadcast found")) == (

        "No live youtube broadcast found"

    )





def test_registry_set_status_updates_snapshot():

    initial = build_initial_status()

    registry = MonitorStatusRegistry(initial)

    registry.set_status("youtube", "active", None)

    registry.set_status("youtube", "idle", "No live youtube broadcast found")

    snapshot = registry.snapshot()

    youtube = next(row for row in snapshot if row["id"] == "youtube")

    assert youtube["status"] == "idle"

    assert youtube["detail"] == "No live youtube broadcast found"


