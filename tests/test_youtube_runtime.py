from unittest.mock import MagicMock, patch

from multistream_revenue_tracker.platforms.youtube_catalog import YoutubeLevelInfo, YoutubeMembershipLevelsError
from multistream_revenue_tracker.platforms.youtube_runtime import YoutubeRuntime


def test_load_levels_sets_catalog():
    runtime = YoutubeRuntime()
    with patch(
        "multistream_revenue_tracker.platforms.youtube_runtime.fetch_membership_levels",
        return_value=[
            YoutubeLevelInfo(id="L1", name="Tier One"),
            YoutubeLevelInfo(id="L2", name="Tier Two"),
        ],
    ):
        runtime.load_levels(MagicMock())
    assert runtime.load_error is None
    assert len(runtime.levels) == 2
    assert runtime.enabled is True


def test_load_levels_soft_failure_sets_load_error():
    runtime = YoutubeRuntime()
    with patch(
        "multistream_revenue_tracker.platforms.youtube_runtime.fetch_membership_levels",
        side_effect=YoutubeMembershipLevelsError("scope missing"),
    ):
        runtime.load_levels(MagicMock())
    assert runtime.levels == []
    assert "scope missing" in (runtime.load_error or "")
    assert runtime.enabled is False


def test_levels_for_ui():
    runtime = YoutubeRuntime()
    runtime.levels = [YoutubeLevelInfo(id="L1", name="Tier One")]
    assert runtime.levels_for_ui() == [{"level_id": "L1", "name": "Tier One"}]


def test_for_ui_includes_levels_when_feature_enabled():
    runtime = YoutubeRuntime()
    runtime.levels = [YoutubeLevelInfo(id="L1", name="Tier One")]
    payload = runtime.for_ui({}, feature_enabled=True)
    assert payload["feature_enabled"] is True
    assert payload["levels"][0]["level_id"] == "L1"


def test_resolve_level_id_logs_unknown_once(caplog):
    runtime = YoutubeRuntime()
    runtime.levels = [YoutubeLevelInfo(id="L1", name="Known")]
    assert runtime.resolve_level_id("Known") == "L1"
    assert runtime.resolve_level_id("Unknown") is None
    assert runtime.resolve_level_id("Unknown") is None
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "Unknown" in warnings[0].message
